# ADR-0144: A Community Cache Hit Is Trusted, and Checked by Sample

Status: accepted

Date: 2026-10-02

Implementation:
- **Accepted 2026-10-02**, as written. **Built 2026-10-04**, released in the version after
  `v0.2.0-beta17`.
  - `tasks/analysis_pipeline.py`: `features_path()` chooses `hit`, `hit (sampled)` or `local`;
    `is_sampled_hit()` takes the first eight bytes of the fingerprint's SHA-256 modulo
    `HIT_SAMPLE_RATE` (50). A trusted hit never calls `precompute_shared`. A sampled hit keeps the
    cache's features and deep scalars as primary, stores the local ones in `local_features` and
    the disagreements in `feature_confidence`, and is not contributed. A miss is unchanged. The
    worker logs `Features path for …: <path>`, and the task result carries `features_path`.
  - `tests/test_features_cache_trust.py` runs `run_track_features` against the test database with
    the decoder rigged to record every call: a trusted hit decodes nothing. Five of its eight tests
    fail on the code this replaced.
  - **The cache's section analysis was being thrown away.** The pipeline fetched it into
    `analysis_detail`, and the next block reset `analysis_detail = None` and recomputed it, so a hit
    *with* cached detail decoded the track anyway, and the cached detail was never stored. Point 3
    now holds for the first time: cached detail is kept, and only a hit without it is left to the
    backfill.
  - **Point 1 named the wrong `features_source`.** It said a hit is written as
    `community_cache:recording` or `community_cache:hash` "as today". That split is ADR-0119's and
    exists for embeddings only; the features lookup is by fingerprint alone and writes
    `community_cache`, which is what it still writes. Asking the corpus by recording for features
    too is not part of this ADR.
  - The MCP tool description that named ReccoBeats (`services/llm/tools.py`) now describes the
    cache and the sample.
  - **Measured on Familiar Server, `v0.2.0-beta18`, 2026-10-04** — the first 20 tracks analysed
    after the update, from `server.log` (`Features path` lines, start-to-end times and peak
    `[MEMORY]` per worker):

    | Path | Tracks | Median time | Median peak memory |
    |---|---|---|---|
    | `hit` | 13 | 7.2 s | 134 MB |
    | `hit (sampled)` | 1 | 38.7 s | 872 MB |
    | `local` | 6 | 44.9 s | 920 MB |

    **The hit rate was 65%, not the 30% the Context measured** (3 in 10 on 2026-10-02): the
    cache had grown. A hit now costs a sixth of a miss in time and a seventh in memory, and at this
    rate the library's mean is about 20 s per track against about 43 s, roughly halving what
    remains of its features phase. One sampled hit in 14 is chance at this size. What is left of a
    hit's 7.2 s is the Follow-up's: starting a process per track (~4.6 s) and the fingerprint's
    decode (~3.4 s).

Extends [ADR-0119](ADR-0119-the-corpus-is-asked-by-recording-before-it-is-asked-by-hash.md) and
[ADR-0138](ADR-0138-a-desktop-server-yields-to-its-owner.md)

## Context

Familiar Server's first real library, 26,839 tracks on a NAS share over SMB, began its features
phase on 2026-10-02 at **47 s per track**: about two weeks of the Mac on mains power for features
alone, with embeddings still to come. ADR-0138 point 4 holds a desktop server to one analysis
worker, so per-track cost is the whole lever. Measured from `server.log` with the per-line times
`v0.2.0-beta13` added (#373), on the first ten tracks:

| | Tracks | Median |
|---|---|---|
| Analysed locally | 7 | 36.6 s |
| **Hit in the community cache** | 3 | **34.7 s** |
| Starting each track's process | — | 4.6 s |

**A cache hit costs what a miss costs.** After the hit, `tasks/analysis_pipeline.py` reaches the
comment "Always run local librosa analysis for features + cross-validation" and decodes and
analyses the track anyway: ~16 s of decoding and features, then silero-vad and the section
analysers, ~11 s. About 28 of a hit's 35 s are spent recomputing what the cache returned, and the
worker's peak memory rises from 110 MB to 870 MB doing it. The cache's values are kept as primary;
the local ones go to `local_features` and `feature_confidence` as `*_disagreement` entries.

**The premise of always running local analysis no longer holds.** It came in with commit
`5196f8c1` (2026-02-24, "cross-validation: local analysis always runs, disagreements flagged when
external features exist"), when the external source was **ReccoBeats**, a third party whose
numbers came from a different algorithm. The ReccoBeats lookup has since been removed — the
comment "Try external feature lookup first (ReccoBeats via Spotify ID)" is now followed by
nothing — so the only external source left is the community cache, whose features were computed
by Familiar itself, on another installation, at the same `FEATURES_VERSION`. Checking them against
the same algorithm on the same audio is mostly recomputing them. And **nothing reads the result**:
no route, screen or tool reads `local_features` or a `*_disagreement` key; the only mention outside
the pipeline is a sentence in an MCP tool's description (`services/llm/tools.py:1029`) that still
names ReccoBeats.

**Two things measured alongside, which bound what this ADR can promise:**

- **Every cache call after the first in a worker failed** (`Event loop is closed`): the singleton's
  HTTP client was bound to the first `asyncio.run()`'s loop. Fixed separately (#378). Until it
  ships, every hit's *analysis detail* lookup has failed, so **how often the cache holds a track's
  section analysis is unknown** — and that decides how much this ADR saves (point 3).
- **The cache rarely has this library.** On the NAS, which analysed the same music, `features_source`
  is `local` for all 26,510 rows and the cache supplied none; on the Mac, 3 of the first 10 tracks
  hit. Trusting a hit speeds up only the hits.

## Decision

1. **A features hit at the current `FEATURES_VERSION` is stored as the track's features, and the
   track is not decoded for features.** The cache's features and deep scalars are written as they
   are, with `features_source` `community_cache:recording` or `community_cache:hash` as today.
   The fingerprint is still computed — it is the cache's key — and MusicBrainz enrichment is
   unchanged.

2. **One hit in fifty is also analysed locally, and its disagreements recorded** in
   `feature_confidence` as now. The sample is chosen from the fingerprint, not at random, so the
   same track is or is not sampled on every installation and every run, and a disagreement can be
   reproduced. A sampled track's local result is **not contributed**: the cache already holds the
   track, and a second submission from the same algorithm is the manufactured agreement clapback's
   `ADR-0008` exists to avoid (ADR-0119 point 4).

3. **A hit's section analysis comes from the cache when the cache has it, and from the backfill
   phase when it does not.** The backfill already selects rows with `analysis_detail IS NULL`
   (`tasks/analysis_queue.py`, `tasks/library_sync.py`) and runs the section analysers locally. A
   hit without cached detail therefore still decodes the track once, later, for sections — but no
   longer runs features and voice detection on it.

4. **A miss, and an unanswered lookup, are analysed locally exactly as now.** ADR-0119 point 4's
   `unanswered ≠ absent` rule is untouched: a lookup that did not complete is not a hit and does
   not skip anything.

5. **The worker logs which path a track took**, `hit`, `hit (sampled)` or `local`, beside the
   per-line times, so the saving is measured from the log rather than estimated.

## Alternatives Considered

- **Keep running local analysis on every hit.** The status quo, and the only way every cached value
  is checked. Rejected: it spends ~28 s per hit computing numbers no reader uses, against a check
  that was designed for a third-party source that has been removed. A sample keeps the check's
  purpose — noticing a bad contributor or a version skew — at a fiftieth of the cost.
- **Stop cross-validating altogether.** The cheapest. Rejected: the cache is written by other
  installations, and once clapback's beets and Picard plug-ins contribute (ADR-0119's Context), by
  other software. Without any local check a bad row would be trusted forever, and nothing would say
  so.
- **Check every hit cheaply, for instance BPM alone.** Rejected: the expensive part is decoding the
  file, which any local check needs. A cheap check on every hit costs most of a full one.
- **Run more workers on Familiar Server.** Rejected for ADR-0138 point 4's reason, which stands: it
  is a machine someone is using. Throughput there comes from doing less per track, not more at once.

## Consequences

- **Positive:** a hit with cached detail stops being decoded at all; a hit without stops running
  features and voice detection. Libraries the cache knows well gain most.
- **Positive:** worker memory on a hit stays near the 110 MB a worker starts at, not 870 MB.
- **Tradeoff:** on this library, where the cache answered 3 tracks in 10 and the NAS got none, the
  overall saving is modest. The ADR is worth more as the cache grows than it is today.
- **Tradeoff:** 49 hits in 50 are trusted unchecked. A wrong row is caught only if it is sampled
  somewhere; the deterministic sample means every installation checks the same 2%, so a bad row
  outside it is never checked by anyone.
- **Follow-up:** measure the hit rate for analysis detail once #378 ships, and record it here. If
  the cache rarely holds detail, point 3's later decode is most of a hit's remaining cost.
- **Follow-up:** the 4.6 s to start a process per track (`max_tasks_per_child=1`), the ~3.4 s
  fingerprint decode, and the embedding phase, still unmeasured, are the next costs per track.
- **Follow-up:** the MCP tool description at `services/llm/tools.py:1029` names ReccoBeats; it is
  corrected when this is built.
