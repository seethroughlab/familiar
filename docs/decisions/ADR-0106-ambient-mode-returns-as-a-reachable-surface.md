# ADR-0106: Ambient Mode Returns as a Reachable Surface

Status: accepted

Date: 2026-09-01

Implementation:
- **Two routes, not three, and a defect fixed on radio.** Reviewed after acceptance against the
  question "could an existing endpoint have done this?". `GET /ambient/descriptor/{track_id}` had no
  caller and is not restored (point 1). `POST /radio/suggestions` now populates `features`, which it
  had answered `null` for since the field existed — `Track` has no `features` attribute and only
  `routes/tracks/listing.py` ever filled one, so radio's own client has never been able to tell you
  a suggestion's key or tempo. The block that fills it was already written out twice in `listing.py`
  and is now `TrackFeaturesResponse.from_analysis`, called from all three sites rather than copied
  into a fourth.
- **The server half is built** on `worktree-ambient-mode-revival`:
  `app/api/routes/listening/ambient.py`, registered through `listening/__init__.py`, with the tag
  metadata and `OPENAPI_TAG_GROUPS` entry in `main.py`, the `VENDORED_TAGS` and
  `ALLOWLISTED_FUNCTIONS` changes, the two `Track.active_filter()` additions in
  `services/ambient.py`, and `tests/test_ambient_routes.py` — 14 tests.
- Verified: both lints pass; 124 tests across the new suite plus `test_ambient_scoring`,
  `test_ranking_profiles`, `test_queue_suggestions` and `test_offline_manifest`, which is the check
  that point 8 held; 98 contract/schema tests unaffected. The four `active_filter` tests were
  confirmed to **fail** against the unfixed service before the fix was applied.
- **The `familiar-apple` half of point 7 is built** on branch `ambient-generated-surface`:
  `ambient` in `filter.tags` and the re-vendored `openapi.json`. Verified where it counts, because
  a `filter.tags` typo is silent — the generated `Client.swift` carries `ambientSeed`,
  `ambientCandidates` and `ambientDescriptor`, and 1,029 Swift tests pass with 50 skipped and no
  failures.
- **Point 5's `Literal`s did what they were for.** `filter_preset` and `intensity` generate as
  `@frozen public enum … : String, Codable, CaseIterable`, so the "RADIO is not radio" mistake
  `ServerRadioSuggestionsSource` documents cannot be made at an ambient call site.
- **`lint_openapi.py`'s cross-check never ran, in either direction.** It resolves the Swift config
  at `parents[3]/familiar-apple`, which from a worktree points inside `.claude/worktrees/`, so it
  takes the silent-skip path and still prints "OpenAPI lint OK". Running it from the main checkout
  would not help until this branch merges, because that checkout's `VENDORED_TAGS` has no
  `ambient` and the check would fail on the drift it is meant to catch. The two lists were compared
  by hand instead: 19 tags and 14 operations, identical on both sides. **The guarantee that these
  cannot drift holds only from the main checkout, and the worktree convention defeats it.**
- **The schema this vendors supersedes the unpushed `sync-schema-adr-0099` branch**, whose single
  commit was itself a schema vendor and which was already behind `origin/main`.
- **It is not the clean superset it first appeared to be, and the way that was missed is the useful
  part.** The first comparison checked which *paths* existed, whether any shared path's content
  differed, and which *components* existed — and found only additions. It did not compare the
  **contents of components present in both**, and three of those changed:
  `SettingsResponse` and `SettingsUpdateRequest` gain three discovery fields, which is safe, and
  **`DiscoverResponse` drops `unheard_tracks` and `deep_cuts` for `rediscovery` and
  `rediscovery_seed_count`** under ADR-0099/0101. `App/Shared/HomeStore.swift:66-67` still reads
  the two removed fields, so re-vendoring the current schema stops the macOS target compiling.
  **Comparing a schema means comparing paths, path contents, component presence *and* component
  contents; three of the four are not enough.**
- The break is a real one and not an artefact: the Mac app is behind the server on ADR-0099/0101's
  discover change, and any branch bringing the schema up to date exposes it. Two sections on Home
  become one list carrying its own provenance, which is a Home-screen decision belonging to
  ADR-0101 rather than to this ADR — so it is recorded here and left to that work.

Amends [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md) point 5, which put
"ambient/generative mode" out of native v1 "and possibly permanently", **and
[ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md) point 4**, which restated the exclusion
with a reason of its own: "out of v1 per ADR-0001 point 5, and `ambient` is deliberately absent from
the generated surface per ADR-0007". Both have to move, and the second is the one easy to miss — it
is where the exclusion acquired its *stated* reason, which this ADR answers. Neither is superseded:
every other exclusion in either list stands. Extends
[ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md), whose engine this makes
reachable again. Paired with [ADR-0107](ADR-0107-ambient-is-a-destination-that-plays.md), which
decides the client half and **executes second** — server work every client inherits comes first.

## Context

Ambient mode shipped on 2026-03-17 (`92f4f262`) and reached its final shape ten days later in
`3e06b6b1`: short windows of harmonically-compatible tracks played at 0.15 volume with eight-second
fades, under a continuously-sounding synthesised drone that glides between the keys of successive
selections, with sparse motif notes filling 25–40 second intermissions in which nothing else sounds.
It is closer to a generative installation than to a music player, and that was the point.

**Nothing ever decided to end it.** It was removed as collateral three times, by three decisions
that were each about something else:

| Date | Commit | What went | The decision it was collateral to |
|---|---|---|---|
| 2026-08-11 | `a124d3ac` (#156) | `FamiliarAmbientSynth/` — the native synth and its plugin | Deleting the Capacitor app (`ADR-0001` point 6) |
| 2026-08-22 | `e6fa37b8` (#190) | `components/Ambient/`, `player/ambient/`, `ambientStore`, `api/ambient.ts` | Removing the web player (`ADR-0058` point 4, `ADR-0070`) |
| 2026-08-29 | `db7a8dc7` (#216) | `backend/app/api/routes/ambient.py` | `ADR-0077` — a surface with no caller is deleted |

The first of those is the one that mattered and the one nobody noticed. The entry point was a row in
the mobile More sheet, rendered only when `getAmbientSynthBridge() !== null`, and the bridge was
registered by exactly one platform. Deleting the Capacitor app therefore did not remove an
affordance — it removed the *condition* under which the affordance rendered. **The feature became
unreachable by any user eleven days before any of its code was deleted**, and the deletions that
followed were each correctly reasoned about what was by then genuinely dead.

`ADR-0077` is explicit that its judgement was about the route and not about the capability:

> The route goes; the service is judged separately. `services/bandcamp.py` and `services/ambient.py`
> stay untouched — both are reached through the MCP tool surface and the recommendation path, which
> is where those capabilities actually live.

That judgement was right, and it is why this ADR is cheap. **The engine survived and grew.**
`backend/app/services/ambient.py` is 753 lines with five importers —
`api/routes/listening/radio.py:30`, `services/offline_manifest.py:26`,
`services/playlist_generation.py:24`, `services/collection_suggestions.py:367` and
`services/llm/handlers/discovery.py:98`. Every function the three deleted routes called is still
public, still exercised and unchanged in contract: `key_compatibility` (line 77), `score_candidate`
(189), `suggest_snippet_window` (331), `get_track_descriptor` (396), `pick_surprise_seed` (412),
`get_candidates` (586) and `find_seed_by_artist` (725).

**Four `ambient` slots look still open**, three of them genuinely so, and none left deliberately for
this — which is the strongest evidence that only the surface was lost:

1. `services/ranking_profiles.py` holds the `AMBIENT` weight profile with its `quiet` and
   `immersive` intensity overrides, pinned against drift by `tests/test_ambient_scoring.py` — 290
   lines, passing. Its module docstring still asserts *"ambient mode is shipped"*, which has been
   false since August and is made true again by this decision rather than corrected away.
2. `db/models/profiles.py`'s `PlayContext` still lists `'ambient'`, `api/routes/tracks/plays.py`
   still accepts it, and it is **already in the vendored Swift schema** as a case of
   `ListenEventRequest.context`. Nothing can emit it.
3. `scripts/lint_profile_contracts.py:40` still allowlists `ambient` as profile-less — though this
   one is a slot in appearance only, and the difference is worth stating because it is the kind of
   thing that gets assumed. Module keys there are *paths* (`get_module_key`), so a bare `"ambient"`
   matched the old top-level `routes/ambient.py` and matches nothing under `listening/`. It has
   exempted nothing since ADR-0077 and would not have silently exempted the restored routes either;
   the lint failed on them until the exemption was written properly. Point 4 deals with it.
4. `POST /offline/manifest` still builds an `AMBIENT` manifest variant **per filter preset**, with
   seed ids for an offline "surprise me". It is in the generated Swift surface and **has no
   consumer** — `ADR-0077` point 4 kept it on the grounds that `ADR-0006` says its client is coming.

So what is missing is a route file and a tag. The measure of this decision is not "rebuild ambient
mode"; it is "stop three endpoints' worth of absence from hiding 753 lines of working engine."

**A premise worth recording, because it is the one that would otherwise be re-derived.**
`ADR-0001` point 5's exclusion list groups ambient mode with the visualizer, the 23 settings panels,
import queues, embedding maps, mixtapes and S3 backup — things excluded because they are large,
management-shaped, or web-only. Ambient mode is none of those. It was excluded for a reason that has
since inverted: it was the one feature whose *implementation* was Capacitor-specific, because the
synth was native iOS code reached over a plugin bridge. Deleting Capacitor is what made it portable.
Mixtapes has already left that list, under `ADR-0014`.

## Decision

1. **Two of the three ambient routes return, under the `ambient` tag, at their original paths.**
   `POST /api/v1/ambient/seed` and `POST /api/v1/ambient/candidates`.
   **`GET /api/v1/ambient/descriptor/{track_id}` does not come back**, and the reason is this ADR's
   own subject applied to itself: `seed` already resolves a descriptor from a track id, so a
   separate lookup has no caller — and a route with no caller is what ADR-0077 deleted all three of
   these for. Restoring it out of fidelity to the deleted file would have reintroduced exactly that
   shape six days after it was removed. `tests/test_ambient_routes.py` asserts its absence, so the
   next reader to compare against the old file finds the reason rather than the gap.
   The file lands at
   `app/api/routes/listening/ambient.py` beside `radio.py` and `offline.py`: `listening/` is a
   module prefix and not a URL one (`ADR-0074` point 5), so the paths are unchanged from what
   `db7a8dc7` deleted.

2. **The exclusion of ambient mode is lifted in both `ADR-0001` point 5 and `ADR-0013` point 4, and
   only that item.** The rest of both lists stands. This is an amendment of one entry, in the manner
   `ADR-0014` used for mixtapes, not a supersession.

3. **`POST /radio/suggestions` is not widened to serve ambient.** It is the obvious alternative — it
   already accepts `profile: "ambient"` and already runs the same engine — and it cannot carry this.
   Precisely, because the loose version of this claim is wrong and would be quoted back:
   `TrackResponse` *does* have a `features: TrackFeaturesResponse | None`, which carries `key`,
   `energy`, `brightness`, `valence` and `instrumentalness`. But it **is never populated on radio's
   path** — `radio.py` builds its response with `TrackResponse.model_validate(track)` and `Track` has
   no `features` attribute, so every suggestion comes back `features: null`; only
   `routes/tracks/listing.py` fills it. And `TrackFeaturesResponse` has no `energy_shape`,
   `dynamic_range_db`, `section_count` or `modal_character` at all. So the drone has no `key` to tune
   to and the window has no `energy_shape` to place itself by. Radio also exposes no `filter_preset`,
   and has no analogue of `/ambient/seed` — surprise-me, seed-by-artist and a pool size *before* a
   session starts have no home on a "what next, given what is playing" endpoint. Fixing all of that
   means either populating `features` on radio's response for every caller or nesting a second
   object beside it, at which point it is the ambient route wearing radio's name. Under `ADR-0072` —
   paths name resources, tags name functions — ambient and radio are two functions over one engine,
   which is exactly what `ADR-0005` decided they were.

4. **The routes stay profile-less, and the exemption is written per-function.** The reason is in
   `radio.py`'s own docstring: ambient ranks purely on musical compatibility with the current track
   and needs no notion of who is listening, which is a contrast radio draws deliberately and does
   not inherit. The two POSTs are POSTs because they carry a body rather than because they mutate
   anything.
   **This point is weaker than it first reads, and should not be leaned on.** `AMBIENT`'s
   `taste_weight` and `max_negative_penalty` are both 0, so a profile id would reorder nothing —
   which cuts both ways: being profile-less costs nothing, and so would being profile-aware, since
   the Swift client sends `X-Profile-ID` on every request regardless. If ambient ever gains a taste
   term this reverses with no argument to overcome. What actually separates ambient from radio is
   point 3's response shape, not this.
   The stale `"ambient"` entry in `lint_profile_contracts.py`'s `ALLOWLISTED_MODULES` is **deleted
   rather than repointed**. It has exempted nothing since ADR-0077, and it would not have covered
   the restored file either: module keys there are *paths*, and the routes now live at
   `listening/ambient`. Two `ALLOWLISTED_FUNCTIONS` entries take its place, which is what that
   file's own comment asks for — ADR-0045 point 2 drives `ALLOWLISTED_MODULES` toward zero, so a new
   module entry moves it the wrong way.

5. **The four defects the deleted routes carried are not restored with them.** Each is a real
   failure that shipped, and each gets a test in `tests/test_ambient_routes.py`:
   - **Ids are `UUID` on the wire, not `str`.** The deleted routes took `track_id: str` and called
     bare `UUID(...)`, so a malformed id raised `ValueError` and surfaced as a 500 where it should
     have been a 422. `radio.py:39-40` records that defect in a comment written while the ambient
     routes were still shipping it next door.
   - **`filter_preset` and `intensity` are `Literal`s, not `Field(pattern=...)`.** A regex
     constraint generates as a bare `String` in Swift, which is how `ServerRadioSuggestionsSource`
     came to need a comment warning that "RADIO" is not "radio". An enum cannot be got wrong.
   - **`/ambient/seed` takes an `intensity` and passes it on.** It declared none and called
     `get_candidates` without one, so the opening candidates of every session were ranked as
     `balanced` however the listener had set it, and only the second batch obeyed.
   - **`/ambient/seed` reports `pool_collapsed` rather than hardcoding `False`**, so a filter that
     leaves nothing to chain to no longer looks, at the moment of starting, exactly like one that
     leaves plenty.

6. **`pick_surprise_seed` and `find_seed_by_artist` gain `Track.active_filter()`.** They never had
   it, so both could return a `MISSING` track — a file no longer on disk, which 404s on stream.
   `get_candidates` was fixed for exactly this and carries a comment saying so; the two seed paths
   were missed, and no current importer calls them, so the bug has been live and unreachable. It is
   worse here than in the candidate path: a bad candidate costs one skipped transition, a bad
   *seed* is a session that cannot start. Verified by reverting the fix and watching the four new
   tests fail.

7. **The `ambient` tag joins the generated surface**, in `scripts/lint_openapi.py`'s
   `VENDORED_TAGS` and in `familiar-apple`'s `openapi-generator-config.yaml` `filter.tags`,
   together, **by tag rather than by operation**. Three operations under one tag with nothing to
   exclude is what a tag is for; `outputs` and `videos` are named operation-by-operation only
   because part of each tag is unwanted. Note the asymmetry that makes this worth stating: a typo in
   `filter.operations` is a hard build failure, while a typo in `filter.tags` is *silent* — the
   generator ignores an unknown tag and the client simply has no such method. Grep the vendored
   `openapi.json` for `ambient_seed` after re-vendoring.

8. **Nothing is added to the ranking engine.** No new weights, no new profile, no schema migration,
   no column. `AMBIENT` stays byte-exact against `tests/test_ambient_scoring.py`, and that suite's
   `TestSuggestSnippetWindow` — which has been guarding a function with no production caller since
   August — gets its caller back.

## Alternatives Considered

**Leave it deleted.** Entirely defensible on the record: three separate reviews removed this code and
none of them was wrong at the time. Rejected because none of them was a decision *about ambient
mode* either, and the sequence has a shape worth refusing — a feature made unreachable by an
unrelated deletion, then correctly pruned as unreachable, produces a deletion no one ever argued for.
The engine's survival through all three is the tell: five callers still want what it computes.

**Serve ambient from `POST /radio/suggestions` with `profile: "ambient"`.** No new routes, no tag,
no schema change, and the Swift client can already call it today — genuinely the cheapest option and
the one to beat. It was reconsidered after this ADR was accepted, which is how the descriptor route
in point 1 came to be dropped, and it survives that second look — but by a narrower margin than the
first pass suggested.

What folding `candidates` into radio would actually cost is three additive changes, two of them
harmless: optional `filter_preset` and `intensity` params whose defaults preserve radio's behaviour
exactly, and populating `features` on the response — which is worth doing regardless, and is done
here, because it was answering `null` for every caller. The third is the objection:
`suggested_start_pct` is a snippet-window hint, and radio plays whole tracks. It would be a field on
a shared contract that exactly one caller can interpret, which is a capability with no caller wearing
a disguise.

`seed` does not fold at all, and that is the firmer half: "where do I start" is a different question
from "what comes after this". Surprise-me and seed-by-artist have no meaning on an endpoint keyed by
`current_track_id`, so folding them means a request model with two disjoint shapes and a path that
names neither.

**Restore the routes but leave the tag ungenerated, and hand-write the Swift client.** Consistent
with `ADR-0007` point 8, which hand-writes streaming, SSE and artwork. Rejected because those are
excluded for reasons that do not apply here — range requests, event streams and binary bodies. Three
JSON operations over plain models are exactly what the generator is for, and a hand-written client
for them would be the only one in the app with no reason for existing.

**Recompute the drone's pitch and the snippet window server-side and return a ready-made plan.**
Tempting, and it would let the client stay ignorant of music theory. Rejected as the wrong side of
`ADR-0006`'s line: the server precomputes *rankings*, which need the library; MIDI note numbers from
a key name and a window from a duration need nothing but the descriptor already in the response.
Putting them on the server would add a round trip to every transition for arithmetic the client can
do, and would make the drone's tuning a deployment rather than a build.

**Revive the web surface too, so the feature exists in both clients.** Rejected: `ADR-0058` made the
web app an administration tool and `ADR-0070` removed its player. There is no audio engine there to
play a snippet and no bridge to synthesise a drone, and re-registering one would reverse two
accepted decisions to gain a copy of a feature nobody asked for on that surface.

## Consequences

- **Positive.** 753 lines of tuned, tested ranking engine become reachable by a client again, having
  been reachable only by radio, the offline manifest and three internal callers since August.
- **Positive.** `tests/test_ambient_scoring.py`'s constraint stops being an orphan. It has been
  pinning `AMBIENT` byte-exact to protect a feature that has not existed for four months — a
  characterisation suite with nothing left to characterise. Point 7 gives it its subject back.
- **Positive.** The 422 in point 5 fixes a defect that was documented in a neighbouring file and
  never repaired, because the file that had it was deleted before anyone got to it.
- **Positive.** Point 6 fixes a bug that is live on `main` right now and that nothing could reach.
  `pick_surprise_seed` and `find_seed_by_artist` have no importer today, so the missing
  `active_filter()` has been a defect waiting for its caller to come back. Reviving a feature
  turned out to be how it was found — which is an argument about deletion policy worth noticing:
  ADR-0077 kept the service and the service kept a bug, undetected precisely because it was
  unreachable.
- **Tradeoff.** Point 7's tag is silent when misspelled, unlike the `operations` form. The mitigation
  is a grep, which is a discipline rather than a gate — as is `lint_openapi.py`'s cross-check, which
  does not run in CI and, as the Implementation block records, does not run from a worktree either.
- **Tradeoff.** The generated Swift surface grows by three operations, and `openapi.json` must be
  re-vendored in `familiar-apple`. This is the cost `ADR-0007` chose deliberately; the cross-check
  in `scripts/lint_openapi.py` means the two repositories cannot drift, but it also means they must
  be changed together and only runs where both are checked out.
- **Tradeoff.** `ADR-0001` point 5 no longer reads as a closed list. It was already not one —
  mixtapes left under `ADR-0014` and casting under `ADR-0031` — but this is the first item to leave
  it by being *revived* rather than by being reconsidered before it was built.
- **Follow-up.** `POST /offline/manifest`'s `AMBIENT` variants still have no consumer, and this ADR
  does not give them one: `ADR-0107` point 5 keeps the first phase online-only. The variants remain
  what `ADR-0077` point 4 called them — kept because their client is coming — and are now one step
  less speculative.
- **Follow-up.** The `'ambient'` `PlayContext` remains unemitted. `ADR-0107` decides that
  deliberately and says why; if that reverses, no schema change is needed, because the enum case is
  already in the vendored schema.
