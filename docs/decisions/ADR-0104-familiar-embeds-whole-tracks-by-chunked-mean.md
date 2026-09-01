# ADR-0104: Familiar Embeds Whole Tracks by Chunked Mean

Status: accepted

Date: 2026-09-01

Implementation:
- Accepted and implemented 2026-09-01 on `adr-0104-chunked-mean`. `extract_embedding`
  (`app/services/analysis.py`) now walks consecutive 480,000-sample windows, mean-pools the raw
  encoder outputs and L2-normalises; `EMBEDDING_VERSION` is 7. The re-analysis of 26,471 embeddings
  drives itself from the existing two-hourly sync — nothing was scheduled for it.
- **Point 2 turned out to change more than pooling.** The previous implementation returned the raw
  encoder output *un-normalised*. Every consumer uses cosine — `cosine_distance` in pgvector,
  `cosine_similarity` in `ego_map.py` and `embedding_map.py`, no L2 or inner-product operator
  anywhere — so normalising at write time is behaviour-preserving, and it makes
  `embedding_map.py:500` normalising again at read time redundant rather than wrong.
- **Point 5's assertion is unreachable in normal operation, deliberately.** Floor division already
  guarantees every window is exactly `window` samples. It exists because the failure it guards is
  silent: `rand_trunc` would start taking a random crop and every embedding would become
  irreproducible without a single type changing.
- **The re-analysis costs six times what the Consequences section estimated.** Deployed and started
  2026-09-01. Measured on the NAS from the database rather than from the sync's own progress:
  **19 tracks in 600 seconds, 31.6s per track, ~230 hours remaining** — nine or ten days of
  background work, not the two or three days 38 hours implied. Nothing is wrong; the estimate was
  taken on an M-series Mac and quoted prominently enough to read as the expected cost.
  **Do not size an analysis pass from a laptop measurement.**
- **The obvious explanation for that gap is not the right one.** CLAP is loaded once per track —
  `load_clap_model()` is `@lru_cache`, but `max_tasks_per_child=1` gives every track a fresh
  interpreter, so the cache never survives; 23 loads were logged for 23 tracks. That looks like the
  dominant cost and is not: the load itself measures **~1.6s** of a 32–46s cycle. The remainder is
  spread across process spawn, the `torch` import, decode and the 32 window inferences, with no
  single term to remove. Raising `max_tasks_per_child` would recover the import and the load —
  perhaps a fifth — at the cost of the memory isolation it exists to provide, and is not obviously
  worth it.
- **The tests could not go where the existing ones are.** `tests/test_analysis.py` opens with
  `pytest.importorskip("librosa")` and CI runs `uv sync --extra dev`, which installs neither librosa
  nor torch — so that whole file is skipped in CI, including both existing `extract_embedding`
  tests. `tests/test_embedding_windowing.py` fakes the two lazily-imported modules instead, so it
  runs in CI against the real function. Verified against the pre-change implementation restored with
  `git show`: 14 of 19 fail, and the 5 that pass are the ones that should (single-window tracks,
  dimensionality, the disabled path, the constant guard).

Extends [ADR-0102](ADR-0102-the-community-cache-gains-a-recording-key.md), whose point 4 made the
CLAP checkpoint pin a long-term commitment, and corrects a premise in it.

Relates to [ADR-0101](ADR-0101-discovery-ranks-against-the-listening-model.md), which made discovery
rank owned music by how it sounds — and therefore made the quality of the embedding a product
concern rather than an implementation detail.

## Context

`extract_embedding` (`app/services/analysis.py:140`) represents a track by **the middle ten seconds
of it**. Lines 170–174 slice `target_sr * 10` samples from the centre and hand only those to CLAP.
A five-minute track is described by 3% of itself, chosen by position.

Measured against production on 2026-09-01: **26,499 active tracks, 26,471 embeddings, all at
`EMBEDDING_VERSION = 6`, none stale.**

### Why the audio is chunked at all — it is not a speed tradeoff

The obvious question is whether ten seconds is a performance compromise. It is not. CLAP's audio
encoder is HTSAT, a Swin-Transformer variant whose positional embeddings are sized for a mel
spectrogram of exactly 1001 × 64 frames. Measured directly:

| input | result |
|---|---|
| 1001 mel frames (10.0s) | accepted |
| 2002 mel frames (20.0s) | rejected |
| 500 mel frames (5.0s) | rejected |

Both runtimes refuse, and PyTorch says why: *"the wav size should be less than or equal to the swin
input size"*. **Ten seconds is the largest thing this model can look at.** Any track longer than that
must be handled as several observations regardless of how much time we are willing to spend.

So the decision is not chunk-or-not. It is what to do with the windows, and today's answer is to
discard all but one.

### What discarding them costs

Two rips of the same recording differ by trim — a few hundred milliseconds of lead-in, a different
fade point. Middle-10s moves its window with that offset; a whole-track mean mostly does not.
Measured across four tracks on 2026-09-01, cosine against the un-offset embedding:

| lead-in added | middle-10s | chunked mean |
|---|---|---|
| +150 ms | 0.984 – 0.994 | 0.9983 – 0.9997 |
| +400 ms | 0.970 – 0.995 | 0.9974 – 0.9995 |
| +1.2 s | **0.950** – 0.992 | 0.9972 – 0.9995 |

A 1.2-second difference in lead-in — well within what two rips of one CD differ by — moves a
middle-10s embedding to 0.95. That is not a rounding error; it is the same distance as a genuinely
different piece of music. It degrades Find Similar and `ADR-0101`'s ranking on any library holding
more than one copy of a record, and it makes cross-installation agreement impossible to distinguish
from disagreement.

### Today's determinism is accidental, and worth understanding before changing it

`ClapFeatureExtractor` defaults to `truncation="rand_trunc"`, which takes a **random** crop when the
input is longer than 480,000 samples. Familiar is nonetheless deterministic — because it pre-truncates
to exactly 480,000 samples at lines 170–174, so `waveform.shape[0] > max_length` is false and the
random branch never executes.

That is a real property but an unguarded one. Anything that changed the slice length would silently
make every embedding non-reproducible, and no test would notice.

### The measurements that make this safe to sequence

Two independent equivalences were verified on 2026-09-01, both on a 323-second track and four others:

- **A hand-rolled librosa mel matches `ClapFeatureExtractor`.** Filter banks differ by 1.15e-09; the
  mel by 7.6e-06 dB peak over a 102 dB range; silence, denormals, DC offset and clipping by exactly
  zero. Full chunked means agree at cosine 1.0000000000 on four of five tracks, worst 0.9999998808.
- **The ONNX export matches PyTorch.** Same comparison, worst 0.9999998808.

For scale: `pgvector` stores `float4`, so a byte-identical vector already round-trips at 0.99999994.
**Both implementation differences are the same order of magnitude as writing the vector to the
database.**

The consequence is that this ADR's re-analysis is paid once and is not invalidated by later moving
off `torch`.

### A premise in ADR-0102 that this contradicts

`ADR-0102` point 4 says the pin `laion/clap-htsat-unfused:v1` is what makes vectors comparable, and
that changing it "means a migration rather than a bump". **The checkpoint was never sufficient.**
This ADR changes every vector while leaving the checkpoint untouched. What actually partitions the
corpus is `EMBEDDING_VERSION`, which `community_cache.py` already sends as `analysis_version`
(lines 107–108, 207–217) — so the mechanism is present, but `ADR-0102` describes the wrong field as
carrying the guarantee.

## Decision

1. **An embedding represents the whole track, as the mean of every 10-second window.** Windows are
   consecutive and **non-overlapping**, each 480,000 samples at 48 kHz mono.

2. **The windows are pooled as a mean of raw encoder outputs, then L2-normalised** — not as a mean of
   already-normalised vectors. The two differ, and this is the one that was measured.

3. **A trailing partial window is dropped; a track shorter than one window is `repeatpad`ed.** Zero-
   padding a tail injects silence into the mean, which is a false claim about the track's content.
   Dropping loses under ten seconds of material that N other windows already represent. Below one
   window there is nothing to drop, so the extractor's existing `repeatpad` applies.

4. **`EMBEDDING_VERSION` bumps to 7, and this is load-bearing rather than hygiene.** It is what makes
   v6 and v7 vectors key separately in the community cache, and it is the only thing that does.
   Shipping the pipeline change without it silently mixes incomparable vectors into a shared corpus.

5. **The window length is asserted, not assumed.** Today's determinism depends on never reaching
   `rand_trunc`'s random branch. The code states that as a check on the slice handed to the
   extractor, so a future change that reintroduces randomness fails loudly instead of quietly making
   every embedding irreproducible.

6. **The identity of an embedding is its pipeline, not its checkpoint.** Correcting `ADR-0102`
   point 4: `EMBEDDING_VERSION` carries the guarantee, and any change to windowing, pooling, mel
   parameters or truncation must bump it even when the checkpoint is untouched.

7. **Re-analysis rides the existing sync phase and is not scheduled.** Phase 3b already selects on
   `embedding_version < EMBEDDING_VERSION` (`analysis_queue.py:99–101`) and aborts after four hours
   (`library_sync.py:446`). Nothing new is built to drive it.

8. **This ADR does not move Familiar off `torch`.** That is a separate decision with a separate cost,
   and the equivalences above are what allow it to be made later without re-analysing a second time.

## Alternatives Considered

- **Keep middle-10s and accept it.** Free, and the embeddings have been serviceable for months.
  Rejected because `ADR-0101` changed what they are for: they now rank a listening model, and the
  measured 0.95 between two rips of one recording is indistinguishable from a different piece of
  music. The defect was tolerable while embeddings only fed Find Similar.

- **Overlapping windows (50% hop).** More thorough sampling, and standard in audio retrieval.
  Rejected as cost without a demonstrated benefit: it doubles inference for a mean that already
  covers every sample of the track exactly once. Worth revisiting only with a retrieval benchmark
  showing it helps, which does not exist here.

- **Zero-pad the trailing partial window instead of dropping it.** Keeps every sample. Rejected
  because the padding is not silence *in the track* — it is silence we invented, and it pulls the
  mean toward "quiet" in proportion to how short the remainder is. A 25-second track would have 20%
  of its representation fabricated.

- **`repeatpad` the trailing window rather than dropping it.** Genuinely defensible — it is what the
  extractor already does below one window, so it would be one rule instead of two, and it discards
  nothing. Rejected for now because it was not measured and point 3's rule was, and because a rule
  that duplicates real audio weights that audio twice in the mean. This is the alternative most
  likely to be right and is recorded as a follow-up rather than dismissed.

- **Normalise each window before averaging.** Weights every window equally regardless of the
  encoder's output magnitude. Not measured, and therefore not chosen; point 2 pins what was tested.
  A defensible variant, and the reason point 6 exists is that switching to it later is a version bump
  rather than a free change.

- **Store all N window vectors instead of a mean.** Richest option, and it would allow "this track
  contains a passage like X". Rejected as a much larger decision than this one: it changes the corpus
  from one vector per recording to many, multiplies storage by ~30, and has no caller. It is a
  different product, not a better version of this.

- **Bump only for newly analysed tracks and leave the 26,471 as they are.** Avoids the re-analysis
  entirely. Rejected because it produces a library where two embeddings cannot be compared and
  nothing records which kind each one is — the precise failure this ADR's point 4 exists to prevent.

## Consequences

- **Positive** — an embedding describes the whole track rather than 3% of it chosen by position.
  Every downstream consumer inherits this: Find Similar, `ADR-0101`'s ranking, the music map,
  suggested tracks and the **15 backend modules** that read `TrackAnalysis.embedding` (measured
  2026-09-01; `CLAUDE.md` says eighteen, which no longer matches).
- **Positive** — offset robustness improves by roughly an order of magnitude (0.95 → 0.997 worst
  observed), which is what makes agreement between two installations holding different rips
  meaningful rather than noise.
- **Positive** — today's accidental determinism becomes a checked property (point 5).
- **Positive** — the equivalences measured here mean the later move off `torch` costs no second
  re-analysis.
- **Tradeoff** — **26,471 embeddings must be recomputed.** Measured on an M-series Mac, a 323-second
  track costs ~3.4s to decode and ~1.8s for 32 windows against ~20ms today, so roughly 5.2s per
  track against 3.4s — on the order of 38 hours. **That figure was wrong for the machine that runs
  it, by a factor of six.** See the Implementation note below: the NAS measures 31.6s per track, so
  the real cost is ~230 hours. The conclusion is unchanged and the estimate should not be trusted.
- **Tradeoff** — inference cost per track rises ~53%. Decode still dominates, so the wall-clock
  increase is smaller than the inference increase suggests.
- **Tradeoff** — v6 and v7 vectors are incomparable, so the library is mixed for the ~ten syncs the
  backfill takes. Similarity results will be inconsistent during that window, and nothing surfaces
  which generation a given track is on.
- **Tradeoff** — chunked mean makes different rips *close*, not identical: 0.997–0.9997, against the
  0.999999 a byte-identical resubmission reaches. Any threshold that treats agreement as proof of
  identical audio must not be set from this number.
- **Follow-up** — whether the trailing window should be `repeatpad`ed rather than dropped, per the
  alternatives above. It needs a measurement, and changing it later is an `EMBEDDING_VERSION` bump.
- **Follow-up** — `ADR-0102` point 4 is accepted and now known to name the wrong field. It should be
  annotated rather than edited, per the ADR rules.
- **Follow-up** — the mixed-generation window above argues for surfacing embedding generation in the
  analysis health view, which currently reports coverage but not which version produced it.
