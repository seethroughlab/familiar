# ADR-0085: Music Videos Are a Mac Function, Not a Visualizer

Status: proposed

Date: 2026-08-18

Extends [ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md), and takes point 2 at its word:
this lands on the Mac and not the phone. Depends on
[ADR-0086](ADR-0086-music-videos-become-a-persisted-resource.md), which **executes first** — the
list endpoint and range support this ADR's surfaces are built on do not exist yet.

## Context

The web app has had music videos since Phase 5, shaped as a **visualizer**: `music-video` is one of
the five ids the registry actually holds (`ADR-0063` records the list;
`packages/frontend/src/components/Visualizer/visualizers/MusicVideo.tsx`, 290 lines), it draws in
the player's artwork area, and it syncs a muted `<video>` to the audio.
`ADR-0064` point 2 already noticed the shape was odd — it is the one built-in that declares no
affinity, because "it plays a video rather than drawing the audio, so no honest claim exists".

That shape does not survive contact with the Mac. A visualizer there is the web bundle in a
`WKWebView` (`ADR-0034`), reached from a menu in the player and confined to the player's background.
It cannot own a fullscreen presentation, it cannot be a sidebar destination, and it cannot carry a
management action like matching a video to a track. Those are the three things wanted.

**The visualizer route is also, today, not actually wired on this host.**
`App/Shared/ServerConfiguration.swift:392` already offers `case musicVideo = "music-video"` in the
native picker, so the affordance is there. But `packages/frontend/src/components/Embed/EmbedVisualizer.tsx:47`
feeds visualizers `currentTime={state.position}` from the native frame, and `MusicVideo.tsx:33`
deliberately ignores that prop — `// Read currentTime directly from store (avoids prop cascade from
FullPlayer)` — reading `usePlayerStore` instead, which on `/visualizer` is never driven. Selecting
Music Video on the Mac gives a video that responds to play and pause and never seeks to the audio.

This is the fourth instance of one shape, and the record should say so plainly: an affordance whose
destination is not mounted, failing silently. `ADR-0017`'s record already lists three —
zero-height virtualised lists (`familiar` #70), a play that posted no intent (#74), and "Listening
Ideas" with no chat to open (#76). The lesson there was to check what an affordance reaches. This
one was reached by a *mirrored list*: `VisualizerChoice` is hand-copied from the page's registry,
and copying the id is exactly the half that cannot tell you whether the thing works.

The synchronisation clock available on this side is `Playhead`
(`familiar-apple/Sources/FamiliarKit/Playhead.swift:31`), published by `FamiliarPlayer` under
`ADR-0041` and updated "roughly four times a second while playing". That is the real bound on how
tight video sync can be, and it is stated here rather than discovered later.

## Decision

1. **A music video is a way of playing a track, not a way of decorating one.** On the Mac it is not
   a visualizer, does not appear in the visualizer picker, and is not a candidate for the
   auto-selector `ADR-0064` point 7 added. It is a mode the current track can be put into, and a
   thing the library can be browsed by.

2. **The library file stays the source of truth; the video is muted.** Audio comes from the existing
   engine, so crossfade (`ADR-0026`), effects (`ADR-0015`), listening events (`ADR-0004`) and
   scrobbling (`ADR-0030`) are untouched, and a play is a play whether or not it was watched.
   Nothing downstream needs to learn that video exists.

3. **Sync is correction-on-threshold against `Playhead`.** `AVPlayer` runs at rate 1.0 while the
   engine plays; on each playhead update, a drift past a threshold triggers a seek with zero
   tolerance in both directions. An explicit seek, a pause, and a track change re-anchor
   immediately rather than waiting for drift. **The threshold must sit comfortably above the
   sampling jitter of a 4 Hz clock**, or the correction fires on its own measurement noise and the
   video stutters — the failure mode is a tighter threshold making sync visibly *worse*.

4. **Sync quality is bounded by that 4 Hz clock, and this ADR does not raise it.** If it reads loose
   in real use, the fix is the engine publishing a host-time-anchored position that `AVPlayer` can
   be scheduled against, which is an audio-engine decision and belongs in its own ADR. Recorded as a
   follow-up so the bound is a known limit rather than a surprise.

5. **Video and the visualizer are mutually exclusive occupants of the player's background.**
   `App/Shared/FullPlayerView.swift:91` already makes that slot *either* the visualizer *or* the
   cover; video is a third occupant of the same slot, and turning it on turns the visualizer off —
   the state is one choice, not two independent toggles beside
   `ServerConfiguration`'s `showsVisualizer(profileID:)`. This is `ADR-0064`'s own defect — album
   art drawn over a playing video, because two places each read "which visualizer is on"
   separately, recorded in that ADR's `## Implementation` — prevented rather than repeated in a
   second place.

6. **The crossfade boundary is not mirrored.** During a crossfade two tracks overlap and only one
   video can be on screen; the video follows the current track and cuts at the boundary. Two
   overlapping videos is not being built, and saying so here stops it being read as a bug.

7. **Four surfaces, all on the Mac** (`ADR-0013` point 2 keeps the phone on the listening path):
   - **A Watch control on `FullPlayerView`**, enabled only when the track has a video, disabled
     with a reason when it does not. Not hidden: the same screen is where you would go to get one.
   - **A Videos row in the sidebar's Library section**, beside Music Map and Discover — a way of
     *finding* something to play, not something done *to* the library, which is the distinction
     `LibrarySidebar.swift` already draws between its Library and Manage sections. Built on
     `ADR-0086` point 3's list endpoint.
   - **Match and download, as an action on a track** — search, choose, download — alongside
     `uploadArtwork` and `removeArtwork` in `App/Shared/RowActions.swift` (`:181`, `:221`), which
     are the closest existing precedent: an external asset attached to a track from its row.
   - **Fullscreen playback** with transport controls, which is the thing a visualizer could never
     be given.

8. **The routing change goes through `LibraryRouting.swift`, and the sidebar row is added by hand.**
   `ADR-0032` point 7's argument applies unchanged: a `SidebarItem` case makes
   `LibraryRoot.init(selecting:)`, `sidebarItem(section:)` and `LibraryView`'s exhaustive switches
   fail to compile until handled. **The sidebar row itself is not one of those sites** —
   `LibrarySidebar.swift:82` records that the rows are literals rather than a `ForEach` over
   `allCases`, so the compiler is no help and a forgotten row is a destination that exists and
   cannot be reached. Stated as a decision point because it is the step this ADR is most likely to
   lose.

9. **The `music-video` visualizer is removed from the web registry**, along with
   `VisualizerChoice.musicVideo` in the native picker. What would remain is the broken copy
   described in `## Context`, advertising on the Mac a function that now exists properly elsewhere.
   It also pays for itself on work already in flight: `docs/REMOVING-THE-WEB-PLAYER.md:68` and `:86`
   name `MusicVideo.tsx → stores/playerStore` as one of the two pins holding `queueStore`
   (`packages/frontend/src/player/queueStore.ts`, 1,193 lines) into the visualizer bundle. Removing
   the visualizer removes the pin. **This point is severable in the sense that 1–8 stand without
   it — but severing it is not free, and two other things now depend on it.**

   - `ADR-0067` says Music Video's absence from the plugin API "is the whole reason this ADR is
     modest", and `ADR-0068` calls it "the one conversion requiring playback state and network
     access in a public plugin API". Keep the web visualizer and both re-expand.
   - Point 10's parity row turns on it. With the web copy gone the row is ❌ in the Web column and
     is excluded from the player's countdown automatically; with it kept the row is ✅ ✅ ❌ and
     **joins** the countdown.

10. **`docs/WEB-PARITY.md` gains a music video row, and it reads `❌ | ✅ | ❌`.** The file has no row
    for this feature at all today, which is how something with five endpoints came to have its
    reachability never discussed. The phone column is the honest one and it is a **loss**, not an
    omission: `App/Shared/FullPlayerView.swift`'s `visualizerChoices` is not inside an
    `#if os(macOS)`, so `VisualizerChoice.musicVideo` is on the iPhone today and point 9 removes it.

    **No new exclusion ADR is needed, provided point 9 is taken.** `ADR-0060` point 1's second rule
    — a row ❌ in the Web column too "is not something the browser provides and cannot be a reason to
    keep it" — applies mechanically, exactly as it did for New Releases detail. `ADR-0060` point 3's
    requirement of an ADR is for adding a row to the *by-decision* list, which this is not.

## Alternatives Considered

**Let the video's own audio play and stand the engine down for the duration.** Much simpler: no sync
problem at all, no 4 Hz bound, no drift correction to tune. Rejected because it silently changes
what the app is doing — effects, crossfade and the spectrum tap all apply to the engine and none
would apply to the video; the audio would be a YouTube encode rather than the file in the library
that was analysed; and "what counts as a play" (`ADR-0004`) would have to be redefined for a stream
that is not your file. The listening history is the asset here, and this would put a hole in it
every time a video was watched.

**Start the video with the audio and never re-seek.** Cheapest correct-looking option, and it holds
for exactly one uninterrupted playthrough. Rejected because any pause, seek, or slow first frame
desynchronises it permanently, and the PWA's own implementation shows the correction is the cheap
part — `MusicVideo.tsx` does it in five lines with a 0.5 s threshold.

**Fix `MusicVideo.tsx` to read its `currentTime` prop and leave it a visualizer.** This would work,
and it is a real option — one line, and the Mac's existing picker entry starts syncing. Rejected
because working is not the same as being the right shape: a visualizer cannot own fullscreen, cannot
be a sidebar destination, and cannot carry the match-and-download action, which together are the
whole request. Worth recording that the cheap fix exists, because if this ADR is rejected that fix
should be applied anyway — the current state advertises something broken.

**Build it on the phone as well.** Deferred rather than rejected. `ADR-0013` point 2 keeps
management off the phone, so at minimum the match-and-download half would not go; and video files
are the largest thing this app would put on a device, landing on the one with least room. If phone
playback is wanted later it extends this ADR rather than reopening it.

**A Videos row under Manage rather than Library.** Arguable, since attaching a video to a track is
management. Rejected on the same reasoning the sidebar already applies to Music Map and Discover:
the *destination* is a way of finding something to play. The management half is the row action in
point 7, which is where the management shape belongs.

## Consequences

- **Positive** — the Mac gains the function the PWA only ever gestured at, in a shape that can hold
  fullscreen, a destination, and an action.
- **Positive** — a fourth instance of the mounted-affordance defect is closed rather than left to be
  found a fifth time, and the mirrored-list mechanism that produced it is named.
- **Positive** — point 9, if taken, removes one of the two Dexie pins that
  `docs/REMOVING-THE-WEB-PLAYER.md` records as blocking the web player's removal.
- **Tradeoff** — sync is bounded by a 4 Hz playhead and will not be frame-accurate. Point 4 says so
  rather than implying otherwise.
- **Tradeoff** — **the phone loses a capability it has today**, rather than simply not gaining one.
  `VisualizerChoice.musicVideo` is in the shared `FullPlayerView`, so an iPhone can select Music
  Video now; point 9 removes it and the four replacement surfaces are Mac-only. What it loses is a
  half-working copy — the same one that never seeks, per `## Context` — but it plays, and it will
  stop. A video downloaded on the Mac is watchable only there.
- **Tradeoff** — video files are large and `videos_path` is already in the S3 backup set
  (`backend/app/services/s3_backup.py:312`), so making videos easier to acquire makes backups grow.
- **Follow-up** — a host-time-anchored position on the audio engine, if point 4's bound proves too
  loose in use.
- **Follow-up** — whether `match_confirmed_by` on `track_videos` is written by point 7's action.
  `ADR-0086`'s own follow-up says the column should be removed if nothing claims it, and this action
  is its only plausible caller.
