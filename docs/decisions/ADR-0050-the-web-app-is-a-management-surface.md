# ADR-0050: The Web App Is a Management Surface, Not a Client

Status: accepted

Date: 2026-08-11

Implementation:
- Accepted 2026-08-11, after the change it describes had shipped and been lived with. The order was
  deliberate: unmounting is one commit to revert, so the decision was made from a working example
  rather than a forecast.
- `familiar` #149 — the parity matrix (`docs/WEB-PARITY.md`), and ~2,560 lines of unreachable code
  deleted, including the ephemeral-playlist system.
- `familiar` #151 — twelve listening-path routes unmounted, Settings promoted from a modal to the
  landing route. Following those routes found three affordances still pointing at them, including a
  mobile bottom bar whose every button was a dead link.
- `familiar` #153 — the matrix updated as point 6 requires.
- **Point 4's permission is now live: the parked browsers may be deleted.** They are named in
  `PARKED_BROWSERS` (`packages/frontend/src/routes.ts`) and amount to roughly 169 files and 35,900
  lines. Not yet done, and deliberately its own change — it is a large diff whose only risk is
  deleting something the matrix got wrong.

Supersedes [ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md) points 1 and 5, and with them
[ADR-0002](ADR-0002-web-app-is-the-management-surface.md) point 2

## Context

Two decisions kept the web app whole, and both are now reversed.

ADR-0002 point 2 said: "Retained: full playback on desktop… The web app remains a complete player at
a computer — **it is not reduced to an admin console**." ADR-0013 point 5 restated that unchanged.
ADR-0013 point 1 then carried it further: "Both clients keep everything. Nothing is removed from the
web app… A browser on any machine stays fully capable, which is the property ADR-0002 valued most and
**which costs nothing to keep**."

**That last clause was the load-bearing one, and it was wrong.** It was a prediction, and it has now
been measured.

### What it cost

In a single working session, with no investment in the web app whatsoever, it produced:

- an entire unreachable subsystem — ephemeral "Unsaved" playlists, whose store's `addPlaylist` had
  zero callers and whose `show-ephemeral-playlist` event was never dispatched, so its sidebar
  section, route and "Save to Library" could never be reached;
- a mobile sheet filtering playlists to `is_auto_generated`, so a hand-made playlist was invisible
  there — the exact inverse of the desktop sidebar;
- an "Add to playlist" picker passing `include_auto=false`, silently excluding six real playlists,
  permanently, since nothing can convert a generated playlist into a regular one;
- a React Query cache collision, two components asking the same key for different data, so which
  answer you got depended on which mounted first;
- **three separate occasions where its E2E specs blocked unrelated PRs** by asserting UI that had
  just been retired;
- roughly 2,150 further lines whose only importers were themselves, including three Settings panels
  superseded by their replacements and never removed.

None of that was work on the web app. All of it was rent.

### And nobody was opening it

Jeff reports more than a week without opening the web client — a period during which it was still
fully featured, so this is not a reaction to the reduction.

The corroborating evidence is weaker than it looks and is recorded here honestly rather than
overstated. **Nothing attributes a play to a client**: `play_events` carries `context`
(`library`/`album`/`playlist`/`radio`/…) and no client field, so "which client played this" is not a
question the data can answer. Twenty-four hours of server logs show no requests for the web app's own
document or assets, against steady API traffic from the Mac — but a PWA with a warm service worker
would not request them anyway. The signals agree; none of them is proof.

### What is already built

Stages 0–2 shipped before this ADR, deliberately: unmounting is one commit to revert, and a decision
about what the web app *is* is better made from a working example than a forecast.

- `docs/WEB-PARITY.md` — every capability across web, Mac and iPhone.
- The dead code above, deleted.
- Twelve routes unmounted; the app opens on Settings.

Writing the matrix immediately justified itself: it caught that `/playlists/:id` was about to be
unmounted on an assumption of parity, when the Mac cannot remove a track from a playlist, rename one,
delete one, or reorder. Following the unmounted routes then found three affordances still pointing at
them, including a mobile bottom bar whose every button was a dead link.

## Decision

1. **The web app is a management surface and a fallback player, not a client.** Its job is what the
   native clients cannot do, plus enough playback that a browser on any machine can still put music
   on.

2. **The listening path belongs to the native clients.** New listening features go to macOS and iOS
   and do not come back to the browser. This finishes what ADR-0002 point 5 started and ADR-0013
   point 1 paused.

3. **What the browser keeps**, each because it is the only place it exists or the only place it
   makes sense:
   - **Settings**, now a page at `/settings` and where the app opens — library scan and sync,
     analysis, backup and restore, Last.fm OAuth, update channel, community cache, diagnostics.
   - **`/library/tracks`**, the fallback player. It also keeps `WebAudioEngine` and the effects chain
     exercised rather than rotting untested.
   - **`/library/artist-cleanup`**, which has no native equivalent.
   - **`/playlists/:id`**, until the Apple clients can edit a playlist.
   - **`/listen/:code`**, since ADR-0037 was rejected and sessions are web-only by decision.

4. **Retired routes are unmounted, not deleted, until this ADR is accepted.** Their components and
   registrations remain, so reverting is one commit. `PARKED_BROWSERS` in
   `packages/frontend/src/routes.ts` names each with where its capability went, and
   `navigationIntegrity.test.ts` allows exactly that set — so an *accidentally* unreachable browser
   still fails the suite. **On acceptance, the parked set may be deleted**; the parity matrix is the
   record from then on.

   **Parked is not the same as deletable, and one entry proves it.** `discover` has no route in the
   app and belongs in `PARKED_BROWSERS`, but `components/Embed/EmbedDiscover.tsx` lazy-imports
   `browsers/DiscoverBrowser/DiscoverBrowser` — it is what both Apple clients render inside their
   `WKWebView`. Deleting it because it is parked would take out Discover on macOS and iOS. Anything
   reachable from the `embed` or `visualizer` entry points is out of scope for deletion however
   unreachable it is from the app's own routes; point 5 is the general form of this.

5. **`/embed` and `/visualizer` are not part of this.** They are consumed by both Apple clients
   (ADR-0016, ADR-0017, ADR-0019, ADR-0033) and pin most of `api/`, `player/`, `db/` and `services/`
   regardless of what the app's own routes do. The web *bundle* is not going anywhere; only the app's
   surface shrinks.

6. **`docs/WEB-PARITY.md` is the reference, and is maintained.** It replaces "keep the code so we
   remember what we had". It is also the native backlog: **"settings only" is not reachable** until
   the Apple clients can edit playlists, edit track metadata, trigger a scan, and create a profile.

## Alternatives Considered

1. **Keep everything and simply stop investing** — ADR-0002 point 3's treatment of mobile web,
   applied to the whole app. Rejected because it is what has been happening, and the list above is
   what it produced. Code that is not maintained but is still built, tested and shipped is not free;
   it fails CI on other people's changes.

2. **Delete the retired surfaces outright rather than unmounting them.** Rejected for now: the
   deletable delta is 169 files and 35,911 lines, which is a large diff to review against a decision
   nobody has lived with. Unmounting is one commit to revert and answers the question within a week.
   Point 4 makes deletion the consequence of accepting this ADR rather than a precondition for it.

3. **Reduce the browser to settings alone, with no player.** Rejected on two grounds: a browser is
   the only way to put music on a machine that has neither app installed, and the effects chain and
   `WebAudioEngine` would then be shipped untested and unexercised. One track list is a cheap way to
   keep both honest.

4. **Port the missing management surfaces to the Mac first, then retire the web app entirely.** The
   right eventual shape, and it is what point 6 records as the backlog. Rejected as a *precondition*
   because it inverts the order: the web app's cost is being paid now, and the porting work is months.

## Consequences

- **Positive** — the maintenance surface shrinks to what is actually used, and the E2E specs that
  repeatedly blocked unrelated PRs go with the routes they covered.
- **Positive** — there is one obvious place for each job, which ends the which-client-do-I-open
  question ADR-0013 point 1 created by design.
- **Positive** — the parity matrix makes the remaining native work explicit rather than implicit in a
  codebase nobody reads as a list.
- **Tradeoff** — a browser can no longer do everything, which is exactly the property ADR-0002 valued
  most. Accepted, because the measurement says nobody was using it.
- **Tradeoff** — the web app's own surface and the native clients will drift, and ADR-0002 point 4
  already said parity is not a goal. The matrix is what stops that drift being *silent*.
- **Follow-up** — the four gaps in point 6, of which playlist editing is cheapest:
  `playlistsUpdatePlaylist` and `playlistsDeletePlaylist` are generated and uncalled, the same shape
  as the create gap ADR-0049 closed.
- **Follow-up** — `packages/ios`, the Capacitor app, is superseded by ADR-0001, has had no meaningful
  commits since May, and still ships **100% of `frontend/src`**. It is now the largest consumer of
  the code this ADR is trying to stop maintaining, and deserves its own decision.
- **Follow-up** — README screenshots and `screenshots.spec.ts` still show retired surfaces. Excluded
  from CI, so nothing is red; stale nonetheless.
- **Follow-up** — nothing attributes a play to a client. If that question matters again, `play_events`
  would need a client field; today it cannot be answered.
