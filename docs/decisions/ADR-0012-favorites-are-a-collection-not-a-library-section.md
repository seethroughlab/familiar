# ADR-0012: Favorites Are a Collection, Not a Library Section

Status: accepted

Date: 2026-07-30

Extends [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md).

Implementation:
- Accepted 2026-07-30.
- Execution order, each phase its own branch: (1) `FavoritesSource` and `FavoritesStore` in
  `FamiliarKit`, no networking and no UI; (2) the generated-client half and the Collections group;
  (3) the row indicator and the menu entry; (4) the full player and the lock screen.
  Phase 1 is first and alone for the reason [ADR-0009](ADR-0009-offline-downloads-are-background-transfers.md)'s
  was: it is where the decisions live — the optimistic toggle, the membership set, the local
  filter — and `swift test` cannot see the app target, so anything left there ships unpinned. The
  four stores already stranded in `App/Shared` are the argument.

## Context

The Apple client can browse tracks, albums, artists and playlists, play them, report what was
listened to, adopt a queue from another device, and — as of [ADR-0009](ADR-0009-offline-downloads-are-background-transfers.md)
phase 4 — download them and play them offline. It cannot mark a track as a favourite, and cannot
see the 1,719 already marked from the web client.

**The API needs no work.** All four favorites operations are already in the generated Swift surface
(`Sources/FamiliarAPI/openapi.json`, 228 paths):

| Path | Methods | Notes |
|---|---|---|
| `/api/v1/favorites` | `get` | `favorites_list_favorites`, paged by `limit`/`offset` |
| `/api/v1/favorites/{track_id}` | `get`, `post`, `delete` | |
| `/api/v1/favorites/{track_id}/toggle` | `post` | |
| `/api/v1/favorites/auto-download` | `get`, `put` | backed by `profile.settings["favorites_auto_download"]` |

They are not among the operations [ADR-0007](ADR-0007-clients-are-generated-from-openapi.md) excludes
(`NOT_GENERATED = {"ambient", "mixtapes", "outputs"}` at `backend/scripts/lint_openapi.py:56`). So
this is ordinary feature work, and the decision is entirely about **where it sits** and **what it
does not do**.

**Two premises worth checking before designing anything, because both are wrong in ways that change
the shape of the work.**

1. **"Favorites is another library list, so it reuses `LibraryStore`."** It is not. `/tracks` pages
   by `page`/`page_size` and accepts `search` plus a dozen filters; `/favorites` pages by
   `limit`/`offset` and accepts **neither a search parameter nor any filter**. It also returns
   `FavoritesListResponse { favorites, total }` rather than `{ items, total }`, and its rows are
   `FavoriteTrackResponse`, which carries `favorited_at` — a field no other track schema has and the
   only sensible default sort. A copy of `LibraryStore` would be wrong in the paging, the envelope,
   the schema and the ordering.

2. **"There is no precedent for where it goes."** There is, and it is unambiguous. The web app's
   sidebar (`packages/frontend/src/components/Sidebar/Sidebar.tsx:58-61`) groups exactly two things
   under `COLLECTION_ITEMS` — Favorites and Downloads — each with a count, separate from the library
   browse items above and the playlists below. Downloads already exists on the native client, placed
   in the toolbar during ADR-0009 phase 4 without reference to that grouping. Favorites is not a new
   destination to find room for; it is the missing half of a pair.

## Decision

1. **Favorites and Downloads are one group, reached from a single "Collections" toolbar entry**,
   which lists both with their counts and pushes the chosen screen. This mirrors the web sidebar's
   grouping rather than inventing a second arrangement for the same two things.

   Not a fifth segment in the browse picker. That picker is four ways of asking the *server* the
   same question, and neither of these is: Favorites is a per-profile collection, Downloads is
   per-device and works with no server at all. A fifth segment also leaves each about 70pt on a
   393pt phone, which is where the labels abbreviate.

   This moves Downloads from where phase 4 put it. That placement was implementation, not a decided
   point — ADR-0009 point 9 makes the downloads list the offline browse surface but says nothing
   about how it is reached — so this supersedes nothing.

2. **`FavoritesStore` is its own type**, reading `favorites_list_favorites` — which pages by
   `limit`/`offset` and returns rows the server has already sorted by `favorited_at` descending. It
   does not share code with `LibraryStore` beyond the cancellation guard every store now needs
   (`NetworkFailure.isCancellation`). The client preserves response order rather than re-sorting:
   `favorited_at` is declared `{"type": "string", "default": ""}` with no `format: date-time`, so it
   arrives as a string, and parsing one to recover an order the server already applied is work that
   can only introduce disagreement.

3. **The collection loads whole, in one request, and filtering is local.** The endpoint offers no
   `search` parameter, and a search box that filtered only the pages already fetched would look like
   a server bug: tracks outside the current window would silently not exist. Loading whole is
   affordable here rather than merely tolerable — `list_favorites`
   (`backend/app/api/routes/favorites.py:64-68`) bounds `limit` at nothing, and its rows carry no
   analysis features, because `features` hangs off `TrackAnalysis` rather than `Track` and so
   serialises as null. 1,719 rows is one response of a few hundred kilobytes. The web client has
   always done exactly this (`favoritesApi.list(10000, 0)`,
   `packages/frontend/src/hooks/useFavorites.ts:48`). If the list grows past what that comfortably
   supports, the fix is a `search` parameter on the endpoint, not a client-side index.

4. **Membership is answered by a complete id snapshot held on the device, not by a request per row.**
   A track row needs to know whether it is a favourite in order to draw the heart, and
   `/favorites/{track_id}` per visible row would be fifty requests per screen of library. The set is
   derived from the single response point 3 describes and then kept, the same shape as
   `Downloads.downloadedIDs` from ADR-0009 phase 4. A partial page cache is not a membership source;
   it would make hearts lie for tracks outside the fetched window — which is the second reason the
   collection is loaded whole, and the one that would still hold if it were not cheap.

5. **Toggling is optimistic, and reconciles from the response.** The heart flips immediately and the
   set is corrected by what `/toggle` returns. A favourite is a low-stakes, high-frequency action;
   waiting a round trip to redraw makes the control feel broken on a slow connection, and getting it
   briefly wrong costs nothing that a corrected set does not fix.

6. **The favourite action appears in the track row menu**, alongside the queue, navigation and
   download entries added in ADR-0009 phase 4 — not as a per-row heart button. This deliberately
   diverges from the web track list, which has more horizontal room and already carries row-level
   controls. On the native phone layout a library list is mostly tracks that are not favourites, and a
   control on every row drowns the titles, which is the same reasoning that keeps the download badge
   invisible until there is something to show. A heart *indicator* on rows that are favourites is not
   a control and does not have this problem.

7. **v1 does not implement `/favorites/auto-download`.** ADR-0009 point 6 defers auto-download
   intent entirely — including `profile.settings["favorites_auto_download"]` by name — on the
   grounds that it needs a background refresh path and a reconciliation policy for intent that
   changed while the device was away. Favouriting a track on the native client will therefore **not**
   download it, while doing the same on the web client will, because `useFavorites` acts on the
   setting. That divergence is deliberate and is recorded here so it is not later mistaken for a bug.

8. **The full-screen player gains a favourite control.** It is the one surface where the current
   track is the entire subject and there is room for a control that is not competing with a list.
   `MPRemoteCommandCenter.likeCommand` is already wired in the engine
   (`NativeAudioEngine.swift:1814` sets `likeCommand.isActive` from `nowPlayingIsFavorite`) and has
   never had a source of truth; this gives it one.

## Alternatives Considered

- **A fifth segment in the browse picker, next to Playlists.** Rejected. It splits the pair the web
  app groups — Downloads would stay in the toolbar and Favorites would sit in the picker, so the two
  collections would be reached two different ways for no reason a listener could infer. It also puts
  a per-profile collection and a per-device one in a control whose other four entries are all server
  queries.

- **Two separate toolbar buttons, a heart and an arrow.** Rejected, though it is the cheapest and
  keeps both at one tap. On a 393pt phone the toolbar would then carry four controls beside the
  title, and neither button can show a count — the counts are what the sidebar uses to make these
  feel like collections rather than actions.

- **Reusing `LibraryStore` with a favourites flag.** Rejected on the evidence above: different
  paging, envelope, schema and sort. The shared-store version would be a sequence of conditionals
  around four unrelated behaviours.

- **Paging the list, and draining pages to build the id set.** Rejected — and it is what this ADR
  said in draft, which is why it is recorded here rather than left out. It is the right shape for
  `/tracks`, where 26,396 rows make one request absurd, and the wrong one for an endpoint with no
  `limit` cap and no analysis features in its rows. It would also have meant two loading modes over
  one endpoint — paged for the list, exhaustive for the membership set — and a filter that could not
  be offered until the second finished. Worth revisiting only if the endpoint grows a cap.

- **A per-row heart button in library lists.** Rejected. Every row would carry a control that is
  inert on the large majority of them, and the row is already carrying a download badge, a duration
  and a title that truncates on a phone. The web client accepts this cost in its denser table/card
  layouts; the native client does not have to copy it. The context menu is where an action that
  applies to a minority of rows belongs, and phase 4 already established that pattern.

- **Fetching favourite status per row on demand.** Rejected. It is a request per visible row, it
  makes scrolling a library issue dozens of requests, and it fails exactly when the collection is
  most useful — offline, where the set is known but the endpoint is not reachable.

- **Implementing auto-download now, since the endpoint exists.** Rejected, and this is the closest
  call. ADR-0009 point 6 defers it on scope rather than principle, and it would be reasonable to
  revisit — but doing it here would mean designing background refresh and intent reconciliation
  inside a feature about a heart icon. It belongs in its own ADR, after ADR-0009 phase 5.

## Consequences

- **Positive:** The client gains the collection with the most existing data behind it — 1,719
  tracks — for no server work, no schema change and no ADR-0007 involvement.
- **Positive:** Downloads acquires the sibling it was always half of, and the native app's
  navigation stops diverging from the web app's for the same two concepts.
- **Positive:** `MPRemoteCommandCenter.likeCommand` gets a source of truth, having been wired since
  the Capacitor port with nothing behind it.
- **Tradeoff:** Downloads moves from one tap to two. Accepted for the grouping and the counts;
  reversible if it proves annoying, since the screen itself does not change.
- **Tradeoff:** Favouriting behaves differently on the two clients until auto-download is decided —
  the web client downloads, the native one does not. Recorded in decision point 7 rather than left
  to be discovered.
- **Tradeoff:** Loading the collection whole, and filtering it locally, is fine at 1,719 rows and
  will not stay fine forever. It is the same unbounded request the web client already makes, and it
  will degrade the same way — gradually, with no failure to notice. The threshold is the endpoint's,
  not the client's: the fix is a `search` parameter, at which point both clients stop fetching
  everything.
- **Follow-up:** Auto-download intent, which ADR-0009 point 6 defers and this ADR declines to
  revisit. It needs a background refresh path and a policy for intent that changed while the device
  was away.
- **Follow-up:** Offline favourites. The set is on the device but the list is not; whether it
  becomes browsable without a server depends on ADR-0011, which is drafted but held on branch
  `docs/adr-0010-0011-held` and so is deliberately not linked here — there is no file to link to
  until it is proposed. If the library is cached whole, favourites become a filter over it rather
  than a second cache.
- **Follow-up:** Whether a favourite should be a queue source — "play my favourites" — which is a
  ranking question closer to [ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md)
  than to this one.
