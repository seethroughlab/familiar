# ADR-0057: The Web App Keeps Only What Has No Native Answer

Status: proposed

Date: 2026-08-16

Extends [ADR-0050](ADR-0050-the-web-app-is-a-management-surface.md), whose point 3 listed what the
browser keeps. It does not reverse that list; it replaces it with a rule that generates it, and
retires the one item whose stated condition has since been met.

## Context

ADR-0050 point 3 named five things the browser keeps, "each because it is the only place it exists
or the only place it makes sense":

> - **Settings** … - **`/library/tracks`**, the fallback player … - **`/library/artist-cleanup`**,
> which has no native equivalent. - **`/playlists/:id`**, until the Apple clients can edit a
> playlist. - **`/listen/:code`**, since ADR-0037 was rejected.

**A list is not a rule, and this one has now failed in both directions.**

**Something on it has expired.** `/playlists/:id` was kept "until the Apple clients can edit a
playlist". They can: create, add, remove, rename, delete and reorder, on both platforms. Nothing
happened when that became true, because a condition written into prose has nobody watching it.

**Something not on it is still mounted.** `App.tsx` serves `/library/artists/:name` and
`/library/albums/:artist/:album`. Neither appears in point 3. They were not decided against; they
were not decided at all, and a list says nothing about what it omits.

**The parity matrix that would have caught both was itself wrong.** Re-verified 2026-08-16: nine
rows were stale, every one understating what native does, each shipped in a numbered PR that did
not update the file. One of those stale rows produced a false statement in a source comment two
repositories away. `docs/WEB-PARITY.md` is named by ADR-0050 point 6 as the reference, and it had
quietly stopped being one.

**And ADR-0050 point 6's own milestone has arrived without being noticed.** It said "settings only"
is not reachable until the Apple clients can edit playlists, edit track metadata, trigger a scan and
create a profile. All four are done — #103, #104, #105, #106 — and the document meant to announce it
was saying the opposite.

So the problem is not which routes to delete. It is that the browser's scope is recorded as an
inventory, and inventories drift silently in a way rules do not.

## Decision

1. **The browser keeps a capability only while it has no native answer.** That is the rule the
   list was an instance of. When the Apple clients gain a capability, the browser's copy becomes a
   second implementation of the same thing, and the second implementation is the one with no user.

2. **Two exceptions, and they are the whole exception list.** A capability stays regardless of
   native parity when it is:
   - **infrastructural** — something a listener does once or rarely, to the *server* rather than to
     their listening: scanning, analysis, backup and restore, profiles, Last.fm, community cache,
     diagnostics, artist cleanup; or
   - **excluded by decision** — listen-together, web-only since ADR-0037 was rejected.

3. **The fallback player is a flat, searchable track list, and nothing else.** `/library/tracks`
   stays for the reason ADR-0050 gave — a guest machine or a second computer can still find a track
   and put music on, and it keeps `WebAudioEngine` and the effects chain exercised rather than
   rotting untested. **Browsing is not part of that.** Artist and album drill-down are the native
   clients' job, and every drill-down screen kept here is a second implementation carrying its own
   tests, loading states and bugs.

4. **`/playlists/:id`, `/library/artists/:name` and `/library/albums/:artist/:album` are removed**,
   with everything that reaches them, in one change. Point 1 retires the first; point 3 retires the
   other two.

5. **A capability and its affordances leave together, in the same commit.** Removing
   `/playlists/:id` alone would leave five "Make a playlist" buttons navigating nowhere, a sidebar
   listing playlists that cannot open, and mobile rows that do nothing. This codebase has shipped
   that defect repeatedly — `familiar` #70, #74, #76, and `.smartPlaylists` falling through to the
   track list — and it is the specific failure this point exists to prevent.

6. **Anything reachable from `/embed` or `/visualizer` is out of scope, always.** ADR-0050 points 4
   and 5 already say this and one entry proves it: `discover` is parked and undeletable because both
   Apple clients render it. Checked for this ADR — `embedBridge.ts` posts a `navigate` intent to the
   *native* side and names API paths, not web routes, so removing the drill-down routes does not
   touch it.

7. **`docs/WEB-PARITY.md` is the trigger, and a row changing to native-✅ is what starts a removal.**
   It failed at this once by going nine rows stale, so it is only usable as a trigger if it is
   maintained with the change rather than after it. That obligation is ADR-0050 point 6's; this
   point states the consequence of ignoring it.

## Alternatives Considered

- **Delete `/playlists/:id` only, and leave the rest.** The smallest defensible step, and exactly
  what ADR-0050 point 3 authorises. Rejected because it answers one route and leaves the same
  question outstanding for the two that were never on the list — and the next person meets the
  identical ambiguity with no more guidance than there is today.

- **Keep artist and album drill-down as part of the fallback player.** Genuinely arguable: from a
  flat list of 26,000 tracks, clicking through to an album is a natural way to find something, and
  removing it makes the guest-machine case worse. Rejected because "find a track and play it" is
  what point 3 justified, search already serves it, and every screen kept for a rare case is
  maintained for all the common ones. Recorded as the real cost of this ADR rather than dismissed.

- **Keep everything until "settings only" ships as one change.** Tidy, and avoids a half-stripped
  intermediate state. Rejected because that is how the browser accumulated two undecided routes in
  the first place: a big-bang removal is always next quarter, and meanwhile the copies drift.

- **Delete the web app.** It is worth naming since the direction points there. Rejected outright by
  the exceptions in point 2 — scanning, backup, profiles and artist cleanup exist nowhere else, and
  ADR-0013 point 2 keeps them off the phone by design.

## Consequences

- **Positive:** the browser's scope is derivable rather than remembered, so a capability arriving
  natively has an obvious consequence instead of needing someone to notice.
- **Positive:** three routes and their components leave, along with the tests and loading states
  they carry.
- **Tradeoff:** the fallback player gets meaningfully worse at browsing. Someone on a guest machine
  who wants "that album" now searches for a track on it. That is the cost, and it is accepted rather
  than argued away.
- **Tradeoff:** the web app can no longer show what a playlist contains, so debugging a playlist
  means opening the Mac app. `/library/tracks` still plays anything.
- **Follow-up:** the seeded-playlist affordances (`useGeneratePlaylist`, five call sites) go with
  `/playlists/:id`. They are a listening feature, they exist natively as of `familiar-apple` #120,
  and their only destination is the route being removed.
- **Follow-up:** `docs/WEB-PARITY.md` gains a row per removal, so the file records where a
  capability went rather than implying the browser still has it.
