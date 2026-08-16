# ADR-0058: The Web App Is an Administration Tool

Status: accepted

Date: 2026-08-16

Extends [ADR-0050](ADR-0050-the-web-app-is-a-management-surface.md) and
[ADR-0057](ADR-0057-the-web-app-keeps-only-what-has-no-native-answer.md). Those said what the
browser is *not* and what it keeps. This says what it is, and schedules the last thing it kept.

## Context

`0050` made the browser a management surface. `0057` gave that a rule and removed the detail routes.
What remains is Settings, `/library/tracks`, `/library/artist-cleanup` and `/listen/:code` — a
management surface still arranged as a music player: it opens on a settings page, and that page is
one scroll of nine sections, five of which are listener preferences.

**The tools mostly exist already.** Four capabilities are built server-side with no web interface,
and two of them already have a client wrapper that nothing calls:

| Endpoint | Gives | State |
|---|---|---|
| `GET /library/stats` | totals, **four separate** pending-analysis queues | `libraryApi.getStats` wraps it, uncalled |
| `GET /tracks/stats/plays` | total plays, seconds listened, unique tracks, top tracks | `profilesApi.getStats` wraps it, uncalled |
| `POST /library/deduplicate/preview` | duplicate candidates | no UI |
| `organizer` — `/templates`, `/preview`, `/track/{id}/preview` | file organisation against a naming template | no UI |

So "library stats" is an unbuilt front end rather than a new feature — the same generated-and-uncalled
shape this codebase keeps finding, this time in the browser.

**One number that does not exist.** There is no artwork-coverage endpoint. `artwork.py` has per-album
status and a batch status POST, but nothing counts albums without art. Recorded because a mock-up
during discussion showed such a tile, and it would otherwise be planned as free.

**And the numbers that did exist were wrong — every one of them.** The first draft of the dashboard
was pointed at the 26k library, and each total disagreed with the screen it links to, because the
stats endpoint counted a different thing:

| field | stats said | the list endpoint said | why |
|---|---|---|---|
| `total_tracks` | 26,488 | 26,422 | no `status == ACTIVE` filter — 66 missing/deleted files counted as library size |
| `total_albums` | 3,873 | 3,927 | `count(distinct Track.album)`, a *string* distinct; the album list groups by `(album_artist, album)` |
| `total_artists` | 3,664 | 3,477 | raw tag strings, so "The Beatles" and "Beatles, The" counted twice; the artist list reads canonical `Artist` (ADR-0052) |

Worse, `albums` / `compilations` / `soundtracks` are not fixable: **nothing in the codebase writes
`Track.album_type`.** Every row keeps the column default, so `albums` is a track count equal to
`total_tracks`, and compilations reads `0` on a library ADR-0052 identified 297 compilations in. It
is a *consumer with no producer* — the mirror of the generated-and-uncalled shape this codebase keeps
finding, and the reason point 6 is written the way it is. A number can be wrong while looking
completely reasonable, and nobody checks a plausible figure.

**And the player is on borrowed time.** Jeff's words: a stop-gap until he is happy with the native
apps. That is a decision this ADR has to carry rather than leave in a message, because everything
below depends on not investing in it.

## Decision

1. **The web app is an administration tool, and opens on a library dashboard.** Not on Settings.
   The first thing an administrator wants is the state of the thing they administer.

2. **Three destinations.** *Library* — dashboard, scan and sync, analysis, pending review, artist
   cleanup. *Tools* — duplicates, organiser, backup and restore, community cache. *Server* — health,
   diagnostics, profiles, Last.fm, API keys, update channel.

3. **The fallback player is temporary and gets no investment.** It stays exactly as `0057` left it —
   a flat searchable track list — appears as a tool rather than a destination, and receives no
   redesign, no new controls and no place on the dashboard. Effort spent on it is spent on something
   scheduled for deletion.

4. **Its removal has a condition that can be checked by reading a file, because prose conditions
   have already failed here.** `0050` point 3 kept `/playlists/:id` "until the Apple clients can edit
   a playlist"; that became true and nothing happened. "Until Jeff is happy with the native apps" is
   worse — subjective as well as unwatched. So: **when `docs/WEB-PARITY.md` shows no ❌ in the Mac and
   iPhone columns of its Listening table, the player is removed.** That file is already obliged to be
   current by `0050` point 6 and is already the removal trigger under `0057` point 7.

5. **Listener preferences leave in two waves.** Now: shuffle weights, radio, audio effects and queue
   sync, which the native clients own per-device (ADR-0029). With the player: offline cache and
   playback, which configure nothing else. Theme outlives both, because it applies to the
   administration interface itself.

6. **A dashboard tile must be backed by a real query, and must agree with the screen it links to.**
   No tile ships whose number is estimated, derived from a sample, or plausible-looking. Where the
   count does not exist, the endpoint comes first — which is why artwork coverage is last rather
   than first, and why no albums/compilations breakdown ships at all.

   The agreement half is the part that was missing, and it is testable: a total on the dashboard
   and the total on the list endpoint behind it are the same number counted the same way, asserted
   against each other rather than against a hard-coded constant. A test that says "expect 3 albums"
   passes under either counting method, which is how this drifted unnoticed for as long as it did.

7. **The four pending-analysis queues are shown separately.** `analysis`, `backfill`, `melodic` and
   `mood_tags` are distinct backlogs with distinct versions, and a single "pending" number hides
   which one is stuck. This is the whole reason to have a dashboard rather than a progress bar.

## Implementation

- **Phase 1** — the dashboard (`familiar` #168, branch `admin/dashboard`). Points 1, 6, 7. Turned
  into a backend change: see the Context table above. `tests/test_library_stats.py` asserts the
  stats endpoint against the list endpoints rather than against constants.
- **Phases 2 and 3 together** — destinations and settings (`familiar` #169, branch
  `admin/destinations`). Points 2, 3, 5. **Deliberately not shipped separately**, though the plan
  had them apart: routing `/tools` and `/server` before moving content into them would have created
  destinations with nothing mounted, which is the defect point 2's own guard exists to prevent.
  Rewriting the sidebar found three affordances that already led nowhere — `/favorites` and
  `/downloads` linked with no route since the ADR-0057 strip, and a mixtape modal whose only setter
  was its own `onClose`. `navigationIntegrity.test.ts` now reads `App.tsx` source and fails on a
  link to an unmounted path; the previous guard read only the registry, which is why affordances
  hardcoded in the component escaped it.
- **Phases 4 and 5** — duplicates and organiser, then artwork coverage. Not started. Both are
  recorded in `UNBUILT_DESTINATION_ITEMS` in `routes.ts` so the gap between this ADR's point 2 and
  the running app is written down rather than rediscovered.

## Alternatives Considered

- **Tidy the settings page and add a stats panel at the top.** Much the cheapest, and it keeps the
  mental model anyone already has. Rejected because the arrangement is the problem: an
  administration tool that opens on a form, with playback controls above library health, is telling
  the operator that its own subject is secondary.

- **A task list rather than a dashboard** — open on what you can *do*, with numbers inside each
  task. Genuinely close, and better for a first-run install where every number is zero. Rejected
  because the recurring question on a live library is "is anything wrong", which a list of actions
  answers only by making you visit each one.

- **Keep the listener preferences until the player is removed**, so settings change once rather than
  twice. Rejected for shuffle weights, radio and audio effects specifically: they do not configure
  the fallback player in any useful sense — they configure a listening experience the browser no
  longer provides — so they are not waiting on anything.

- **Remove the player now and skip the intermediate state.** Tempting, and it is where this ends.
  Rejected because it is Jeff's call on his own listening, the native apps still have ❌ rows in the
  Listening table, and a guest machine is a real case until they do not.

## Consequences

- **Positive:** four built capabilities become reachable, two of them by calling a wrapper that
  already exists.
- **Positive:** the operator sees which of the four analysis backlogs is stuck, which today requires
  reading the database.
- **Positive:** the player's removal has a trigger someone will actually notice, which is the defect
  `0050` point 3 shipped.
- **Tradeoff:** a browser-only listener loses shuffle weights, radio and audio effects. They exist on
  the native clients and not here, and this makes that division explicit rather than gradual.
- **Tradeoff:** settings move twice — once now, once when the player goes. Accepted rather than
  delaying the first move to avoid the second.
- **Positive:** `/library/stats` now agrees with `/library/albums` and `/library/artists`, with
  `tests/test_library_stats.py` asserting the agreement rather than the arithmetic. The endpoint had
  been wrong on all three totals for as long as nothing called it — which is the actual cost of a
  generated-and-uncalled capability: it is not merely unused, it is unverified.
- **Follow-up:** `Track.album_type` has no writer. Either the scanner sets it — MusicBrainz release
  types are already fetched in `metadata/musicbrainz.py`, which penalises compilations, so the data
  is at hand — or the column and the three response fields go. Until then `albums`, `compilations`
  and `soundtracks` stay on the wire, deprecated in the model and in `types/index.ts`, displayed
  nowhere. Removing them is a cross-repo break: `library` is a generated tag under ADR-0007.
- **Follow-up:** artwork coverage needs a count endpoint before its tile can exist.
- **Follow-up:** when the player is removed, `0050`'s reasoning that it keeps `WebAudioEngine` and
  the effects chain "exercised rather than rotting untested" needs re-examining rather than assuming
  it evaporates — `/embed` and `/visualizer` pin much of `player/` regardless.
