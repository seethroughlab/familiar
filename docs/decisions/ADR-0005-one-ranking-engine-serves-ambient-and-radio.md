# ADR-0005: One Ranking Engine Serves Both Ambient and Radio

Status: accepted

Date: 2026-07-26

Implementation:
- Shipped: `services/ranking_profiles.py` carries the profiles, with `RADIO` at line 92 and the
  registry at 121; ambient and radio both rank through it, and the negative signal from ADR-0004
  arrives via `ambient._negative_signal`.
- Recorded late, on 2026-08-02. The decision had been executed for weeks with no `Implementation:`
  block, which is how it came to look unbuilt in a survey of the set.
- **Both follow-ups below are blocked until roughly 2026-09-01**, and not for the reason the dates
  suggest. ADR-0004's data did not begin accumulating usably until `familiar` #57 landed on
  2026-08-01: 795 of the first 823 rows carry a completion ratio of ~0.5 by construction. Tuning
  `RADIO` against them would fit the weights to a client bug. See ADR-0004's Implementation section
  for the measurement and for `FEEDBACK_TRUSTWORTHY_SINCE`, which any tuning query must apply.

Extends [ADR-0004](ADR-0004-listening-feedback-is-event-sourced.md).

## Context

The feature that drove daily listening toward Spotify is its habit of inserting tracks it expects you
to like into a playing queue. Familiar has no equivalent — but it is much closer to one than it
appears.

`backend/app/services/ambient.py` is **already a working "what should play next" engine**, built for
ambient/generative mode. Its two-phase design is exactly what a radio feature needs:

1. **Candidate retrieval.** `get_candidates()` fetches the top 150 by HNSW cosine distance over
   `TrackAnalysis.embedding` — a 512-dim CLAP vector indexed by
   `ix_track_analysis_embedding_hnsw (embedding vector_cosine_ops)`. It falls back to random ordering
   when the current track has no embedding.

2. **Scoring.** `score_candidate()` (`ambient.py:179`) combines a genuine Camelot-style harmonic
   compatibility table (`key_compatibility()` at `ambient.py:67` — same key 1.0, relative
   major/minor 0.9, perfect fifth 0.8, parallel 0.7, two steps 0.5, else 0.2) with energy,
   embedding distance, vocal, brightness, valence, and dynamic-range terms, then applies a BPM-delta
   penalty (−0.15 beyond 40 BPM) and an artist cooldown (−0.25).

This is a tuned transition engine. What makes it *ambient* rather than *general* is only its
weighting and filtering:

```python
weights = {"key": 0.30, "energy": 0.20, "embedding": 0.15,
           "vocal": 0.10, "brightness": 0.10, "valence": 0.10, "dr": 0.05}
vocal_score = inst * 0.7 + (1.0 - speech) * 0.3   # actively penalizes vocals
```

and `pick_surprise_seed()` filters `instrumentalness >= 0.5, speechiness <= 0.5, energy <= 0.7`.

Crucially, **the weights are already swapped by listening intensity** (`ambient.py:231-237`, where
`quiet` and `immersive` each override two weights). Named weight profiles are an extension of a
mechanism that exists, not a new concept.

What the engine lacks for radio use is a **taste** dimension: it ranks by musical compatibility with
the current track, with no notion of what this listener actually likes. That signal does exist —
`backend/app/api/routes/tracks/listing.py` implements weighted shuffle presets
(`rediscover | fresh_finds | comfort_zone | deep_dive`) as `ShufflePresetWeights` over
`ProfilePlayHistory` and `ProfileFavorite`, using Efraimidis-Spirakis weighted reservoir sampling
(`key = ln(u)/w`) followed by `_apply_artist_variety()` spacing. It is simply not connected to the
candidate scorer.

## Decision

Generalise the existing engine into named weight profiles rather than building a second recommender.

1. **Extract the weight dictionary in `score_candidate()` into named profiles.** `AMBIENT` reproduces
   today's behaviour **exactly**, including the intensity overrides, the quiet-energy bonus, and the
   minor-key bonus. `RADIO` permits vocals and weights taste.

2. **`AMBIENT` behaviour is regression-locked.** Ambient mode is a shipped feature; this refactor
   must not change a single ranking it produces. Tests assert equivalence against the current
   implementation before the profile split lands.

3. **Add a taste term to `RADIO`, reusing `ShufflePresetWeights`** from
   `backend/app/api/routes/tracks/listing.py` rather than reimplementing play-count/recency/favourite
   weighting. That math is written, tested, and already tuned for this library.

4. **Add a negative term from [ADR-0004](ADR-0004-listening-feedback-is-event-sourced.md)'s
   `PlayEvent`** — skipped and rejected tracks are demoted, with rejection weighted more heavily than
   a skip. Until events accumulate this term is inert, which is acceptable and expected.

5. **New endpoint `POST /api/v1/queue/suggestions`** in a new `backend/app/api/routes/queue.py`,
   taking the current track, recent track and artist IDs, and a weight profile. Unlike the ambient
   routes it is **profile-aware and requires `RequiredProfile`** — note that `ambient` is currently
   allowlisted as profile-less in `backend/scripts/lint_profile_contracts.py`, and the new module
   must not inherit that exemption.

6. **Client insertion mirrors `AmbientCoordinator`.** `packages/frontend/src/player/ambient/AmbientCoordinator.ts`
   (615 lines) already prefetches two to three candidates ahead and manages transitions; the radio
   controller follows that shape. The insertion primitive also exists —
   `queueStore.addToQueue(track, insertIndex?, shuffleInsertPosition?)`.

7. **Inserted tracks are visually distinguishable in the queue**, with accept and reject affordances
   feeding [ADR-0004](ADR-0004-listening-feedback-is-event-sourced.md). A suggestion the listener
   cannot identify as a suggestion cannot be evaluated by them or learned from.

8. **Insertion fires every N tracks, N = 4, not user-configurable initially.** Resolved at
   acceptance; it had been left open and decision point 6 cannot be built without it. Inserting only
   on queue exhaustion was rejected because the queue does not empty in normal use — a library queue
   is a lazy reservoir over the whole collection (`queueStore.setLazyQueue`), so the trigger would
   effectively never fire. A setting was rejected for now on the grounds that a preference nobody
   finds does not help; N is a constant to be revisited once ADR-0004 data shows whether 4 is right.

## Alternatives Considered

- **Build a separate recommender service.** Rejected. It would duplicate a tuned scorer, a harmonic
  compatibility table, and an HNSW retrieval path that already work, and the two would drift.
- **Generate queue continuations with the LLM.** Rejected for per-track insertion — latency and cost
  per track are wrong for something firing every few songs. The LLM path (`chat.py`, `queue_tracks`)
  remains the right tool for explicit conversational requests.
- **Use collaborative filtering.** Rejected. Single-user local libraries have no collaborative
  signal.
- **Use only `/tracks/{id}/similar`.** Rejected. Raw embedding nearest-neighbour ignores key, energy,
  and BPM continuity — the things that make an insertion feel deliberate rather than random.
- **Fork `ambient.py` into a second module.** Rejected. Two copies of the Camelot table and the
  scoring loop is the outcome this ADR exists to prevent.

## Consequences

- **Positive:** The highest-value missing feature is largely a reweighting of existing, tuned code.
- **Positive:** Ambient mode and radio share one scorer, so improvements to harmonic matching or
  transition quality benefit both.
- **Positive:** It lands in the web app immediately and the native clients from
  [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md) inherit it with no extra work,
  because it is entirely server-side.
- **Tradeoff:** Refactoring a shipped feature's scorer risks regressing it. Mitigated by decision
  point 2, which is a hard requirement rather than an aspiration.
- **Tradeoff:** Quality will be mediocre at launch — the taste and negative terms need data.
  [ADR-0004](ADR-0004-listening-feedback-is-event-sourced.md) shipping first is what shortens that
  window.
- **Tradeoff:** Tracks lacking `TrackAnalysis` embeddings or features cannot be ranked and fall back
  to random. Coverage across the library determines perceived quality.
- **Follow-up:** Tune `RADIO` weights against real listening once
  [ADR-0004](ADR-0004-listening-feedback-is-event-sourced.md) data exists. Initial values are a
  starting guess.
- **Follow-up:** Revisit `N = 4` and whether the cadence should become user-configurable, once
  ADR-0004 data shows how often suggestions are accepted. Decided at acceptance as decision point 8.
