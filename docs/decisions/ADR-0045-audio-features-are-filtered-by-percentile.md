# ADR-0045: Audio Features Are Filtered by Percentile, Not by Absolute Value

Status: proposed

Date: 2026-08-08

## Context

**Familiar's 0–1 audio features are real measurements on scales that do not mean what their names
imply.** Measured across the 25,697 analysed tracks in the live library:

| feature | p10 | p50 | p90 | distinct values |
|---|---|---|---|---|
| `energy` | 0.700 | 0.826 | 0.898 | 25,590 |
| `valence` | 0.665 | 0.848 | 0.985 | 23,640 |
| `danceability` | 0.096 | 0.149 | 0.206 | 25,583 |
| `acousticness` | 0.391 | 0.491 | 0.578 | 25,614 |

The signal is there — roughly 25,600 distinct values each — but it is compressed into a narrow band
that sits nowhere near the middle of 0–1. **This is arithmetic, not accident.**
`services/analysis.py:550` computes `energy = clip((rms_db + 60) / 54, 0, 1)`, so a typical master
at −15 dBFS yields 0.83, which is the observed median. `danceability` is `mean(shared["pulse"])` —
the raw mean of librosa's predominant-local-pulse curve, a quantity that naturally lands near 0.15
and was never on a perceptual scale.

**The consequence is that an absolute threshold carries almost no information**, and it fails in
both directions. Verified by counting:

| filter | matches | share of library |
|---|---|---|
| `energy≥0.6 and valence≥0.6` | 23,761 | **92.5%** |
| `energy≥0.85 and valence≥0.85` | 5,956 | 23.2% |
| `energy≥0.85` | 9,520 | 37.0% |
| `danceability≥0.4` | **5** | **0.02%** |

**This is not hypothetical.** The MCP spike in `familiar` #114 asked a model for "something upbeat
and happy" with no calibration guidance; it filtered `energy≥0.6, valence≥0.6` and got 92.5% of the
library — and nothing in the result would have told the listener that. Asked for "really danceable",
a *correctly calibrated* model chose 0.4 and got five tracks, because there is no threshold that
works.

**A workaround already exists and is not enough.**
[ADR-0042](ADR-0042-the-llm-surface-is-an-mcp-server.md) point 3 requires tool descriptions to tell
a model to call `get_feature_distribution` before choosing a bound, and the spike showed it works:
blind thresholding went from 3 occurrences to 0. But it only helps the one consumer that has a model
in the loop reading descriptions. **It does nothing for the other consumers**, which have no
opportunity to calibrate at all: the `fx`/`fy` generic filter axes on `GET /tracks`, smart-playlist
rule fields, the ambient/radio ranking engine, and the Music Map's aggregation endpoints.

**Four facts established by measurement before writing this, because each one shapes the decision:**

- **Percentile boundaries are cheap.** All six percentiles (`p10, p25, p50, p75, p90, p95`) for six
  features, in **one query over 25,697 rows: 252 ms**. This is a derived quantity, not a stored one.
- **Translating a percentile to a raw threshold keeps the existing indexes.** `energy >= 0.898`
  returns 2,558 rows in **3 ms**, and `ix_track_analysis_energy`, `_valence`, `_bpm`, `_swing_ratio`
  and `_brightness` already exist. A per-track percentile column would need new columns and new
  indexes to reach the same place.
- **Per-track `percent_rank()` is 53 ms for one feature** — affordable, but it has to be recomputed
  whenever the library changes, and it stores a value that goes stale silently.
- **Feature filtering is implemented four times.** `routes/tracks/listing.py:108`, `:348`, `:506`
  and `services/llm/handlers/search.py:393` each write `TrackAnalysis.energy >= energy_min`
  independently. Adding percentiles naively would make it five.

**A premise that was tested and failed, recorded so it is not retried.** Percentiles do *not* rescue
every feature. `instrumentalness` is exactly 1.0 for 25,661 of 25,697 tracks and `speechiness`
exactly 0.0 for the same set, because silero-VAD was being driven with a v4 signature against a v5
model (`familiar` #116). Fixing the call does not help: silero detects **speech, not singing**, so
obviously vocal tracks score 0.0012–0.0017 against instrumental at 0.0006. **The percentile of a
near-constant is noise**, and presenting it as a rank would dress up a dead feature as a live one.
Point 7 below is a direct consequence.

## Decision

1. **Percentile *boundaries* are computed and cached; per-track percentile ranks are not stored.**
   A small cached table — features × a fixed set of percentiles — is refreshed on a schedule and
   after analysis runs. At 252 ms for six features this is affordable to recompute often, and it
   holds tens of rows rather than 26,000.

2. **A percentile request is translated into a raw threshold before it reaches the query.**
   `energy_min_pct=90` becomes `TrackAnalysis.energy >= 0.898`. This is what keeps the existing
   indexes doing the work — 3 ms, measured — and it means percentile support adds no new query
   shape, no new index, and no new column.

3. **Audio-feature filtering gets one implementation, and the four existing copies collapse into
   it.** This is a prerequisite rather than a tidy-up: percentiles added on top of four independent
   copies would produce four subtly different translations, and this codebase has already been bitten
   by one rule copied into divergent subsets.

4. **Percentile parameters sit alongside absolute ones rather than replacing them.** Absolute bounds
   remain correct for the cases that genuinely mean an absolute quantity — `bpm`, and any caller
   reproducing a stored filter. Removing them would also break every existing smart playlist. The
   percentile form is the one documented as the default for perceptual language.

5. **`get_feature_distribution` returns the boundaries**, so the tool that already exists to answer
   "what does high mean here" answers it in the units the filter now speaks. ADR-0042 point 3's
   guidance stays, and becomes cheaper to follow rather than redundant.

6. **No `ANALYSIS_VERSION` bump and no re-analysis.** Everything here is derived from data already
   in `track_analysis`. This is the decisive practical advantage over rescaling at extraction time,
   and it means the fix reaches the whole library the day it ships.

7. **A feature whose distribution is degenerate is withdrawn, not ranked.** If the interquartile
   range is empty — `instrumentalness` and `speechiness` today — the feature is excluded from
   percentile filtering and from the surfaces that offer it, rather than being served as a rank
   computed over a constant. **Degeneracy is detectable from the same boundary computation** that
   point 1 already runs, so this is a property the system can check rather than a list someone
   maintains.

8. **The boundaries are per-installation, and that is the point.** They describe *this* library, so
   "high energy" means something different on a folk collection and an EDM collection without anyone
   configuring anything. Nothing is shared between installations and nothing is seeded.

## Alternatives Considered

**Store a per-track `percent_rank()` column for each feature.** The obvious shape, and it makes
sorting by rank trivial. Measured at 53 ms per feature, so computing it is not the objection.
Rejected because it stores a derived value that every insert invalidates: adding one album silently
makes 26,000 stored ranks slightly wrong, and nothing would detect that. It also needs a new column
and a new index per feature to match the 3 ms the existing indexes already deliver, in exchange for
a number that can be derived on demand.

**Rescale the features at extraction time so the stored 0–1 values are perceptually meaningful.**
The most honest fix in principle — `energy` would then actually mean energy, and every consumer
benefits with no API change at all. Rejected on two grounds. It requires re-analysing ~26K tracks on
a machine that is also the music server and the CI runner, and more importantly it bakes one
library's distribution into the definition: the constants would be fitted to this collection, and
would be wrong for anyone else's, which is the same failure one layer down.

**Leave it, and rely on ADR-0042 point 3's calibration guidance.** It works — the spike measured
blind thresholding falling from 3 to 0 — and it costs nothing to keep. Rejected as a complete answer
because it only reaches the consumer with a language model in it. The `fx`/`fy` axes, smart-playlist
rules and the ranking engine have no way to calibrate, and a listener building a smart playlist by
hand gets no guidance at all.

**Use z-scores rather than percentiles.** Cheaper to maintain — mean and standard deviation are two
numbers per feature — and it handles unbounded features like `harmonic_complexity` naturally.
Rejected because these distributions are visibly skewed and clipped: `valence` has p90 at 0.985
against a hard ceiling of 1.0, so a z-score above the mean is compressed against the boundary and
does not correspond to rank. Percentiles are distribution-free, which is exactly the property needed
when the underlying shape is this irregular.

**Expose percentiles only to the LLM tools.** Much smaller, and it targets the consumer where the
failure was actually observed. Rejected because the failure was observed there only because that is
where someone looked. The same wrong thresholds are reachable from the filter UI and from smart
playlists, and a decision that fixes one caller leaves the shared defect in place.

## Consequences

- **Positive.** "High energy" becomes expressible. A request for the top decile returns the top
  decile on any library, rather than 37% of this one.
- **Positive.** It ships without re-analysis, so it reaches all 25,697 analysed tracks immediately.
- **Positive.** Point 3 leaves one place where audio-feature filtering happens, which is where the
  next feature predicate should be added.
- **Positive.** Point 7 turns a class of silent data failure into a detectable condition. The
  `instrumentalness` case took a spike, a distribution query and a model-signature investigation to
  find; the same check would have surfaced it from the boundaries alone.
- **Tradeoff.** Two ways to express the same filter, and callers must understand which they want.
  Point 4 accepts this deliberately — the alternative breaks every stored smart playlist — but
  "why did `energy_min=0.9` and `energy_min_pct=90` give different answers" is a question someone
  will ask.
- **Tradeoff.** Cached boundaries are stale between refreshes. Harmless at 26K tracks, where one
  album moves nothing; the failure mode to watch is a *small* new library, where each import shifts
  the distribution materially and a stale cache is proportionally wrong.
- **Tradeoff.** Point 3 touches four call sites across two subsystems, one of which is the LLM tool
  path that `ADR-0042` is concurrently proposing to re-host. Whichever lands second inherits the
  merge.
- **Follow-up.** `bpm` is quantised to **33 distinct values** across the whole library — librosa's
  geometric tempo lattice, `…117.45, 123.05, 129.20…`. Percentiles are the wrong tool for it and it
  is excluded here, but a BPM filter that cannot distinguish 122 from 124 is worth its own look.
- **Follow-up.** If this lands, `ADR-0042` point 3's calibration guidance becomes a convenience
  rather than a load-bearing requirement, and that ADR's tradeoff about description quality softens.
  It does not become wrong, and it should not be edited until this is accepted.
- **Follow-up.** `instrumentalness` and `speechiness` stay withdrawn under point 7 until a vocal
  detector suited to music exists (`familiar` #116). Point 7 is what stops them quietly returning
  as ranks in the meantime.
