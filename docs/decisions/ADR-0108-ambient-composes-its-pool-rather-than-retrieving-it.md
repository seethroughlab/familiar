# ADR-0108: Ambient Composes Its Pool Rather Than Retrieving It

Status: accepted

Date: 2026-09-04

Extends [ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md)

Implementation:
- **Written after its implementation shipped, which inverts the intended order.** Points 1–4 and 7–11
  landed in `fe481563` (#282) and points 5–6 in `282393b3` (#284), both on 2026-09-04, before this
  record existed. That is the failure ADR-0106 point 8 also demonstrates, one level up: the decisions
  were real and the record was not written, so the only account of them was in commit messages. The
  code was never evidence of approval; approval came separately, on review.
- **Point 12 is implemented** — the one point that had no code when this was written. `profile` is
  gone from `get_radio_suggestions`' published `input_schema` in `services/llm/tools.py`, so a model
  is no longer offered a choice, and `_get_radio_suggestions` now always ranks with `RADIO`. The
  keyword survives in the handler signature deliberately: `executor.py` dispatches with
  `handler(**tool_input)`, so a stale or hallucinated `profile` argument would otherwise become a
  `TypeError` surfaced to the model as a failed tool call. It is accepted and ignored instead.

## Context

Ambient's candidate pool was a pure pgvector HNSW nearest-neighbour search on the *currently playing*
track, and at the default `filter_preset="all"` the only conditions were active / not-recently-played
/ long enough / energy-not-null. That is right for "more of this" and wrong for "stay ambient": from a
rock seed every one of the 150 candidates is rock. `score_candidate` then measures energy, brightness
and valence as **proximity to the current track** — nothing absolute — so a session was a random walk
with no anchor, and it walked out of ambient territory and stayed out.

Five premises in the existing record are false. Rule 5 requires saying so rather than leaving them to
be re-derived.

1. **ADR-0106 point 8 is false.** It states: *"Nothing is added to the ranking engine. No new weights,
   no new profile, no schema migration, no column. `AMBIENT` stays byte-exact."* Commit `4968b966`
   (2026-09-03) added `liveliness_ceiling=0.55` and `liveliness_penalty=0.30` to `AMBIENT`
   (`ranking_profiles.py:185-186`) — two days after ADR-0106 was accepted, and never amended. The
   correction existed only in a commit message and a test docstring. **This ADR supersedes that
   point**; ADR-0106 otherwise stands.

2. **ADR-0107 point 10 is false.** It states the aesthetic is preserved exactly, *"snippet volume
   0.15"*, and that *"nothing changes the synth's mix at runtime"*. Snippet volume is now a listener
   facing slider because 0.15 was inaudible on real speakers, the drone ducks per window, and
   `setDroneTexture` varies the bed between tracks. Noted here because it is the same failure mode as
   point 1 and not because this ADR changes it.

3. **A penalty was tried first, and could not have worked.** `liveliness_penalty` was aimed at exactly
   this problem. **A penalty can only reorder the pool it is given** — handed 150 rock tracks it
   selects the quietest rock track, which is still rock. Recorded so this is not revisited as "just
   tune the weight harder".

4. **Absolute feature thresholds were tried and are useless on a real library.** Measured across
   ~26,000 analysed tracks: energy p5 = 0.648, p50 = 0.826. The entire library sits above the
   0.40–0.65 band that "quiet" intuitively suggests, so any fixed threshold admits everything or
   nothing. Adjacency has to be relative to the library it is measured in.

5. **`instrumentalness` and `speechiness` cannot contribute, and one shipped feature depends on them
   anyway.** Of the **25,694** active tracks carrying the columns, **25,620 (99.7%)** hold exactly
   `instrumentalness = 1.000` and `speechiness = 0.000`; p5, p50 and p95 are identical on both. Only
   74 differ, because silero-VAD detects speech rather than singing. Consequently
   `FILTER_PRESETS["instrumental"]` (`services/ambient.py:324`, gating `min_instrumentalness: 0.5,
   max_speechiness: 0.3`) is **effectively inert**: 36 tracks fail the first gate and 3 the second, so
   choosing it removes about 0.15% of the library and reads to the listener as doing nothing. CLAP
   `mood_tags` cannot substitute — they are populated on 26,430 of 26,434 tracks and carry no usable
   signal, with `blues` tagged on 13,749 tracks and `country` on 13,010, every confidence sitting at
   ~0.45–0.51.

## Decision

1. **Ambient-adjacency is one measured score, `ambient_fitness`.** Energy 0.45, tempo 0.25,
   acousticness 0.30, in `services/ambient_fitness.py`. It is **percentile-relative**: the calibration
   is measured from the library's own distribution (full at p10, zero at p60) rather than fixed, per
   Context 4.

2. **A ceiling, not a target, and NULL reads as neutral.** One-sided on energy and tempo, so a
   0.10-energy drone does not score *worse* than a 0.25 one — proximity-to-a-target was right for
   picking a representative seed and wrong as a floor. Missing analysis scores 0.5, not 0.0, so a
   track whose analyser never wrote `acousticness` is not silently exiled.

3. **One definition in two forms.** A Python form and a SQL form, tested against each other. They
   replace three inline copies, two of which disagreed: seed selection scored energy as proximity to
   0.25 with a slope, artist-seed selection targeted 0.4 with none, and the offline manifest inlined
   the gates a third time under a docstring claiming they matched.

4. **The pool is composed from three branches rather than retrieved from one**, for profiles that opt
   in: fit-and-near (continuity), **fit-from-anywhere** (the branch that breaks the lock-in, because
   eligibility must not depend on what is playing), and excursions.

5. **The fit-from-anywhere branch is drawn weighted by fitness, not uniformly.** Sampling proportional
   to `fitness ** 6` by Efraimidis–Spirakis (`random() ** (1/w)`), one expression and no extra pass. A
   floor decides what is *allowed* and says nothing about what is *likely*; a uniform draw over a
   bottom-heavy band returns the band's floor. Measured: 3,475 tracks clear a 0.60 floor but 2,766 of
   them sit below 0.80 against 203 above 0.90, so roughly five rows in ninety came from the genuinely
   ambient end.

6. **The floor stays low and weighting does the work.** Raising it to 0.80 was measured and rejected —
   see Alternatives. **A weight of zero must never mean ineligible**, or the exponent becomes a
   second, undeclared floor.

7. **Excursions are drawn from *below* the floor, and one candidate in eight is one.** Not merely
   ungated: from a calm seed an ungated neighbour query returns calm tracks which are all also fit, so
   dedup leaves nothing and a correctly-working session produces no variety at all. The slot is forced
   regardless of score, because this is a decision about texture rather than compatibility — otherwise
   the liveliness penalty scores the excursion out of existence.

8. **The excursion rate is a property of every prefix, not of the request.** The client takes three
   candidates at seed and two per top-up, and both are constants in the *other* repository. The phase
   comes from `blake2b` of the track id — **never the builtin `hash()`**, which is PYTHONHASHSEED
   salted, so two uvicorn workers would disagree about the same track and the bug would not reproduce
   locally.

9. **Nothing is added to the wire.** An excursion arrives as an ordinary candidate with a low
   compatibility score. An `is_excursion` flag would force an OpenAPI change and a Swift client
   regeneration for a field with no consumer. The composition is logged server-side instead.

10. **Profiles opt in, at the level of the profile.** `RankingProfile.pool` is `None` for `RADIO` and
    `PLAYLIST`, which keeps their query byte-identical. `get_candidates` is shared with radio and the
    MCP discovery tool under ADR-0005, and a previous defect here was closed with the note "this was
    never an ambient bug".

11. **It degrades rather than collapsing.** If the fit branches return nothing, fall back to
    neighbours and log a warning. An empty pool surfaces to the listener as "Session ended", which is
    worse than the bug being fixed.

12. **`profile="ambient"` is dropped from the MCP discovery tool.** `llm/handlers/discovery.py:105`
    accepts it and would inherit the composed pool, returning library-wide quiet tracks from a tool
    whose docstring promises the seed's neighbours plus the listener's taste. Two of the three
    branches deliberately ignore the seed, so the tool's stated contract would be false. Radio remains
    its only profile.

## Alternatives Considered

**Raise the fitness floor instead of weighting the draw.** Measured directly and rejected. At 0.80 the
eligible band falls from 3,475 tracks to 709 — it buys the same mix by making five sixths of the
eligible library ineligible, and long sessions would circle a few hundred records. Weighting reaches
the same distribution while nothing stops being reachable: the expected share of picks above 0.90 goes
from 5.8% to roughly 23%, and above 0.80 from 20% to about 50%.

**Tune `liveliness_penalty` harder.** Cannot work, per Context 3. This is a pool problem and a penalty
is a scoring tool.

**Put the fitness predicate in a single ANN query's `WHERE`.** HNSW **post-filters** — it returns its
`ef_search` nearest rows and *then* applies the predicate. From a rock seed that is nearly empty,
which is precisely the case the change exists for.

**Put fitness in `ORDER BY` of the same query.** Disqualifies the index and full-scans ~26,000
vectors on every top-up.

**Use CLAP `mood_tags` or a text embedding of "ambient" for adjacency.** Rejected on measurement, per
Context 5 — the stored tags are uncalibrated zero-shot similarity with half the library tagged
`blues` and half `country` at indistinguishable confidences.

**Use `instrumentalness` to keep the pool instrumental.** Impossible, per Context 5: the column is
constant for 99.7% of the library. This is the honest answer to "why does ambient play vocal tracks"
and the reason the score omits both columns rather than weighting them at zero — a weight of zero
would imply the input carries signal that is merely unwanted here.

**Add an `is_excursion` flag to the response.** Rejected under point 9 — a schema and client
regeneration for a field nothing reads.

## Consequences

- **Positive.** Eligibility stops depending on what is playing, which is the actual defect. A session
  seeded on anything converges into ambient territory instead of out of it, and the top of the
  ranking — Philip Glass, Boards of Canada, Satie, Eno/Moebius/Roedelius, Autechre — is reached often
  rather than by accident.
- **Positive.** One definition of adjacency replaces three divergent copies, so the two seed paths and
  the offline manifest can no longer disagree about the same track.
- **Tradeoff.** Three queries per top-up instead of one. Mitigated by sharing `base_conditions` and
  hoisting a single `SET LOCAL hnsw.ef_search`, and by the fit-from-anywhere branch avoiding the index
  entirely — but it is three round trips where there was one.
- **Tradeoff.** The excursion rate is fixed at one in eight by construction rather than by listening.
  It is a single constant, and the first report from real use is what should move it.
- **Tradeoff.** A percentile-relative calibration means the same track can change fitness as the
  library grows. This is intended — adjacency is a claim about *this* library — but it makes
  fixtures sensitive: a two-valued test library makes every percentile coincide, the calibration
  reports itself degenerate and silently falls back to defaults, and the resulting test proves
  nothing. `test_ambient_pool_weighting.py` records two versions that failed this way.
- **Follow-up.** ADR-0106 gains `Status: accepted` unchanged with a note that point 8 is superseded
  here. ADR-0107 point 10 is left contradicted and unamended; correcting it needs its own ADR, since
  it is a claim about the client's aesthetic rather than about ranking.
- **Follow-up.** `FILTER_PRESETS["instrumental"]` filters ~0.15% of the library and should be removed
  or backed by a working detector. Removing it is a user-visible change to a shipped control and is
  deliberately not bundled here.
- **Follow-up.** ADR-0006's offline manifest ranks a fixed downloaded set with `score_candidate` and
  has **no pool to compose**, so none of this reaches it. A small absolute `ambient_fitness` term in
  the score is the only lever that would; until then, "identical by construction rather than two
  implementations intending to agree" holds for the score and not for the pool.
