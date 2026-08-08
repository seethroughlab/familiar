# ADR-0047: Feature Scales Are Corrected in Place, Not Re-Extracted

Status: proposed

Date: 2026-08-08

Extends [ADR-0046](ADR-0046-audio-features-are-filtered-by-percentile.md)

## Context

[ADR-0046](ADR-0046-audio-features-are-filtered-by-percentile.md) fixes how a caller *asks* for a
feature: percentile boundaries instead of absolute thresholds, so "high energy" means the top decile
of this library rather than a number that happens to sit near the median. It deliberately left the
stored values alone, and rejected rescaling at extraction time partly on the cost of re-analysing
~26,000 tracks.

**That rejection was reopened by an offer to pay the cost — and the investigation that followed
found the cost mostly does not need paying.** Both halves of that finding are worth recording.

### Re-analysis is far more expensive than the ADR assumed

- **`ANALYSIS_VERSION` no longer exists.** It is `FEATURES_VERSION = 8` (`backend/app/config.py:114`),
  split per phase alongside `EMBEDDING_VERSION` and `MELODIC_VERSION`. A vestigial
  `Settings.analysis_version` survives at `config.py:46` with no readers, and `CLAUDE.md`,
  `AGENTS.md` and `VERSIONING.md` still instruct bumping the old constant and show `= 3`. Anyone
  following the documented procedure today would edit a dead value and watch nothing happen.
- **Analysis runs on one worker.** `max_analysis_workers = 1` (`config.py:88`) feeding a
  `ProcessPoolExecutor(max_workers=1, max_tasks_per_child=1)` (`services/background/executors.py:70-78`)
  — a fresh interpreter spawn per track. Nothing anywhere sets `MAX_ANALYSIS_WORKERS`.
- **A features pass aborts after 8 hours** (`services/tasks/library_sync.py:355`), so a full
  re-analysis is 5–10 consecutive sync runs, not one job.
- **It re-runs work unrelated to any scalar**: AcoustID fingerprinting in a subprocess, a MusicBrainz
  lookup rate-limited to 1 req/s, and community-cache network calls. The rate-limited I/O, not the
  DSP, likely dominates.
- The last bump was **2026-02-24, ~17 months ago**. Nothing has exercised this path at 26K scale on
  the current code.

### But every scale problem except one is a transform over a stored number

Each miscalibrated feature is a **monotonic function of a scalar already in `track_analysis`**:

| feature | what is stored | why the scale misleads |
|---|---|---|
| `energy` | `clip((rms_db + 60) / 54, 0, 1)` (`analysis.py:548-550`) | a fixed −60…−6 dBFS window; modern masters at −15 dBFS all land ≈0.83 |
| `danceability` | `mean(librosa.beat.plp(...))` (`analysis.py:557-558`) | PLP is peak-normalised per track, so its **mean** is inherently ≈0.15 — never a calibrated 0–1 |
| `swing_ratio` | onset position, gated `0.3 < x < 0.8`, default 0.5 (`analyzers.py:901-919`) | **the observed 0.300–0.800 range is the gate itself**, not the music |
| `syncopation` | `mean(dist to 16th grid) × 4` (`analyzers.py:921-939`) | maximum possible min-distance is 0.125, so it **cannot exceed ~0.5 by construction** |
| `harmonic_complexity` | chord changes per bar, unscaled (`analyzers.py:297-298`) | unbounded; observed max 14.0 while its neighbours claim 0–1 |
| `brightness` | `min(centroid / 8000, 1.0)` (`analyzers.py:1121-1123`) | while `analysis.py:632` uses `centroid/(sr/2)*2` for valence's own brightness term — **two brightness scales in one codebase** |

None of these requires touching audio. There is precedent for the correction living in code rather
than in the data: **`valence` already applies a post-hoc rescaler**, `sign(c)·|c|^0.6 · 1.8` at
`analysis.py:661`, for exactly this reason.

### The one genuine exception

**`bpm` cannot be fixed this way.** `librosa.feature.tempo` at `sr=22050` with the default
`hop_length=512` (`analysis.py:343-345`) admits only `BPM(k) = 60·sr/hop/k = 2583.984 / k` — k=21
gives 123.05, k=22 gives 117.45, matching the 33 distinct values observed across 25,697 tracks. A
lattice **destroys information**, and no transform over the stored value recovers what was never
measured. Fixing it means re-extraction, which makes it a cost decision rather than a scaling one.

## Decision

1. **Feature scales are corrected by transform, not by re-extraction.** Every feature named above is
   a monotonic function of a stored scalar, so the correction is arithmetic. **No
   `FEATURES_VERSION` bump, and no re-analysis**, which means the fix reaches all 25,697 analysed
   tracks the day it ships rather than over the following fortnight.

2. **The raw column stays raw; the correction is applied on read.** Stored values remain exactly
   what the extractor measured, and the corrected scale is derived when serving. This keeps the
   change reversible, keeps the correction reviewable as code rather than as a one-way migration,
   and means a better correction later is a code change rather than another data migration.

3. **A feature declares its real range, and that declaration is the single source of truth.**
   `syncopation` is 0–0.5 by construction, `swing_ratio` is 0.3–0.8 by its gate,
   `harmonic_complexity` is unbounded. Today these are implicit in the extraction code and
   contradicted by the API, which presents them beside genuinely 0–1 values with nothing marking the
   difference. The same declaration is what [ADR-0046](ADR-0046-audio-features-are-filtered-by-percentile.md)
   point 7 already needs to detect a degenerate feature, so it is one mechanism, not two.

4. **The two brightness formulas are reconciled to one.** `analyzers.py:1121` divides the spectral
   centroid by a fixed 8 kHz; `analysis.py:632` divides by `sr/2` and doubles it. They disagree for
   every track, and one of them feeds a stored column while the other feeds `valence`. Which
   survives is an implementation choice; **having two is not**.

5. **`bpm` is excluded, named, and deferred to its own decision.** It is the sole feature whose
   correction requires re-extraction, and therefore the sole one whose price is a multi-day
   re-analysis. Bundling it here would attach that cost to a change that otherwise has none.

6. **This does not replace [ADR-0046](ADR-0046-audio-features-are-filtered-by-percentile.md), and
   cannot.** Percentiles answer *"what counts as high energy in this collection"*, which remains
   library-specific no matter how well the scale is calibrated — a folk library and an EDM library
   have different top deciles of a perfectly scaled feature. **0046 fixes how you ask; this fixes
   what the number means.** Both are needed, and the second is not a workaround for the first.

7. **The stale versioning documentation is corrected as part of this.** `CLAUDE.md`, `AGENTS.md` and
   `VERSIONING.md` describe a constant that no longer exists. This ADR is the first work in a year
   to depend on knowing how re-analysis is triggered, and it found the documented procedure to be
   wrong — leaving it wrong would guarantee the next person repeats the investigation.

## Alternatives Considered

**Rescale at extraction and re-analyse the library.** The version this ADR was asked to consider,
and the most honest in principle: the stored numbers would then mean what their names say, with no
read-time layer at all. Rejected because the investigation showed the cost is real and the benefit
is not — one worker with a per-track interpreter spawn, an 8-hour phase cap forcing 5–10 runs, and a
pass that re-does AcoustID and MusicBrainz I/O to change arithmetic. **Paying days of compute for a
result obtainable by a pure function of a number already stored is the wrong trade**, and it would
have been made on an assumption rather than a measurement.

**Rewrite the stored values with a migration.** No read-time layer, no ongoing cost, and a one-time
`UPDATE` is minutes rather than days. Genuinely tempting. Rejected because it discards the raw
measurement: every future refinement of the correction would then compose on top of the previous
one, and there would be no way to check a corrected value against what the extractor actually
produced. Point 2 keeps the audit trail for the price of an arithmetic operation per read.

**Do nothing beyond ADR-0046.** Percentiles already make queries behave correctly, which was the
observed failure. Rejected because percentiles fix *filtering* and leave everything that
**displays** a feature still lying — the Music Map axes, any UI showing "energy 0.83", and every
comparison between two features on incompatible scales. It also leaves point 4's contradiction in
place, which is a latent bug independent of presentation.

**Fix each feature ad hoc, where it is consumed.** Smallest possible diff per site, no new concept.
Rejected because it is exactly how the codebase arrived at two brightness formulas, and because
ADR-0046 point 3 is simultaneously consolidating four duplicate implementations of feature
filtering. Adding per-site corrections while removing per-site filters would be pulling in two
directions at once.

## Consequences

- **Positive.** Every feature the API serves can be given an honest scale without re-analysing
  anything, so the correction reaches the whole library immediately.
- **Positive.** Point 3's range declaration is a single mechanism serving two decisions — this one
  and ADR-0046 point 7's degeneracy check — rather than two overlapping ones.
- **Positive.** Point 4 removes a genuine contradiction: two functions in one codebase computing
  "brightness" differently, one feeding a column and one feeding `valence`.
- **Positive.** Keeping raw values means a wrong correction is a code fix, not a data-recovery job.
- **Tradeoff.** A stored value and a served value now differ, so anyone reading the database
  directly sees numbers that do not match the API. Point 2 accepts this deliberately, but it needs
  saying out loud: the column is the measurement, not the answer.
- **Tradeoff.** Read-time arithmetic on every feature served, forever, in exchange for never paying
  a migration. Negligible per row; it is a permanent cost against a one-time one, and that is the
  shape of the trade.
- **Tradeoff.** `bpm` stays wrong. Its 33 values remain the worst scale problem in the library, and
  point 5 defers rather than solves it.
- **Follow-up.** The `bpm` decision. Cheap options exist and should be weighed before assuming a
  full re-analysis: passing `hop_length=256` or `128` to both `onset_strength` and `feature.tempo`,
  parabolic interpolation of the tempogram peak, or **free** — `60 / median(diff(beat_times))` from
  the PLP beats already computed at `analysis.py:348-351`.
- **Follow-up.** Whether the corrected scale should also be written back to a second column, if
  read-time arithmetic ever shows up in a profile. Nothing suggests it will.
- **Follow-up.** `instrumentalness` and `speechiness` are excluded from all of this: they are not
  miscalibrated but dead, pending a vocal detector suited to music (`familiar` #116). A scale
  correction cannot rescue a constant.
