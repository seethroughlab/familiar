# ADR-0085: Music Videos Are a Mac Function, Not a Visualizer

Status: accepted

Date: 2026-08-18

Extends [ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md), and takes point 2 at its word:
this lands on the Mac and not the phone. Depends on
[ADR-0086](ADR-0086-music-videos-become-a-persisted-resource.md), which **executes first** — the
list endpoint and range support this ADR's surfaces are built on do not exist yet.

## Context

The web app had music videos from Phase 5, shaped as a **visualizer**: `music-video` was one of the
five ids the registry held, it drew in the player's artwork area, and it synced a muted `<video>` to
the audio. `ADR-0064` point 2 had already noticed the shape was odd — it is the one built-in that
declares no affinity, because "it plays a video rather than drawing the audio, so no honest claim
exists".

That shape does not survive contact with the Mac. A visualizer there is the web bundle in a
`WKWebView` (`ADR-0034`), reached from a menu in the player and confined to the player's background.
It cannot own a fullscreen presentation, it cannot be a sidebar destination, and it cannot carry a
management action like matching a video to a track. Those are the three things wanted.

**The premise this ADR was drafted on has since been overtaken, and the correction makes the case
stronger rather than weaker.** As drafted, the argument was that the visualizer route was wired but
broken: `packages/frontend/src/components/Embed/EmbedVisualizer.tsx` fed visualizers
`currentTime` from the native frame, and `MusicVideo.tsx` deliberately ignored that prop —
`// Read currentTime directly from store (avoids prop cascade from FullPlayer)` — reading
`usePlayerStore`, which on `/visualizer` is never driven. Selecting Music Video on the Mac gave a
video that responded to play and pause and never seeked.

**That file no longer exists.** `MusicVideo.tsx` was deleted on 2026-08-23 in `c00d99f` (`familiar`
#192), when `ADR-0087`/`ADR-0088` turned every visualizer into a sandboxed document; the whole
`packages/frontend/src/player/` tree went with it in #190 and #194. So the web copy is gone — as
collateral of another decision, not by anyone deciding anything about music video — and the shipped
document set is `beat-tiles`, `lyric-storm`, `lyrics`, `reactive-terrain` and `spectrum`, with no
`music-video` in `App/Shared/Visualizers.bundle/` either.

**What remains is the affordance without any destination at all.**
`App/Shared/ServerConfiguration.swift:404` still offers `case musicVideo = "music-video"`, and
`App/Shared/FullPlayerView.swift:284` still uses `VisualizerChoice.allCases` as the picker's fallback
until the page publishes its catalogue. Choosing it now selects an id nothing serves. Meanwhile
`app/api/routes/videos.py` is mounted and working with **zero callers in any repo** — the web
client's `videosApi` (`packages/frontend/src/api/integrations.ts:21`) has none either.

This is the fourth instance of one shape, and the record should say so plainly: an affordance whose
destination is not mounted, failing silently. `ADR-0017`'s record already lists three —
zero-height virtualised lists (`familiar` #70), a play that posted no intent (#74), and "Listening
Ideas" with no chat to open (#76). The lesson there was to check what an affordance reaches. This
one was reached by a *mirrored list*: `VisualizerChoice` is hand-copied from the page's registry,
and copying the id is exactly the half that cannot tell you whether the thing works. The mirror has
since drifted in both directions at once — it still names `music-video`, which is gone, and it does
not name `spectrum`, which ships.

The synchronisation clock available on this side is `Playhead`
(`familiar-apple/Sources/FamiliarKit/Playhead.swift:32`), published by `FamiliarPlayer` under
`ADR-0041` and updated "roughly four times a second while playing". That is the real bound on how
tight video sync can be, and it is stated here rather than discovered later.

## Implementation

Points 1–3, 5, 7 and 9–10 shipped on `music-videos` in `familiar-apple`, with the web and parity
halves on `adr/accept-0085-0086` in `familiar`.

Point 3 needed its stated prerequisite first: `onSeek` was a single closure already held by casting,
so a second consumer would have silently displaced it. It is now keyed registration. The sync
decision lives in `VideoSyncPolicy` in FamiliarKit rather than beside the `AVPlayer`, because
`swift test` cannot see `App/Shared` and the threshold is the part worth pinning.

Point 5 is `PlayerBackdrop`, an enum rather than a second boolean, so the impossible state cannot be
written down. The stored preference migrates from the old `showsVisualizer` key rather than resetting.

Point 7's fourth surface — **fullscreen playback — is delivered by the full player itself rather than
as a separate presentation.** On macOS `FullPlayerView` is already a window takeover with transport
controls (`LibraryView`'s `.overlay`), so the video backdrop there *is* the fullscreen surface. No
`fullScreenCover` or second window was added. Worth stating plainly, because the ADR's phrasing reads
as though a fifth thing was built and it was not.

Two things the build caught rather than review: adding the destination broke
`NavigationCommandTests`, which holds a byte-for-byte copy of the server's `NAVIGATION_DESTINATIONS`
— the drift guard working. And `fullPlayer` is shared by both presentations, so an inline `#if`
around its arguments left the trailing modifiers attached to nothing on iOS, which surfaces as an
unrelated-looking type-inference error.

Point 9 cost less than written: `MusicVideo.tsx` had already gone, so the web half was one dead
constant and two stale comments. The trap was the one the ADR did name — `visualizerID` is stored as
a bare `String` and never round-trips through the enum, so a profile holding `"music-video"` needed
an explicit rewrite or the fix would have created a smaller version of the defect it closed.

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

   **Re-anchoring on an explicit seek needs `onSeek` to become multi-consumer first.**
   `FamiliarPlayer.onSeek` is a single closure property and it is **already taken** by casting
   (`App/Shared/FamiliarApp.swift:199-201`), so a video player that assigns it silently breaks
   casting — the mounted-affordance shape again, pointed the other way. Convert it to attach/detach
   registration, following what `EmbeddedVisualizerView`'s pump already does for `onAnalysisFrame`,
   rather than adding a second bespoke hook beside it. Stated as part of this point because it is a
   prerequisite for it, not a cleanup.

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

9. **`VisualizerChoice.musicVideo` is removed from the native picker, and the web app's leftover
   `music-video` strings go with it.** The web half of this point has already happened without
   anyone deciding it — see `## Context` — so what is left is four lines in `familiar`
   (`Visualizer/constants.ts:15`, `VisualizerPicker.tsx:19`, and stale comments at
   `hooks/useAutoSelectedVisualizer.ts:35` and its test) and three in `familiar-apple`
   (`ServerConfiguration.swift:404`, `:420`, `:430`). Two things about the native removal are worth
   stating, because neither is caught by the compiler:

   - `FullPlayerView.swift:296` maps a catalogue entry back through `VisualizerChoice` for its
     glyph, falling through to a generic puzzle piece. A stale id there is silent, not a build error.
   - `ServerConfiguration.swift:206-220` stores `visualizerID` as a plain `String` and never
     round-trips it through the enum, so **a profile whose `UserDefaults` still holds
     `"music-video"` keeps returning it after the case is deleted** and selects nothing. That needs
     an explicit reset to `defaultID`, or this ADR closes a mounted-affordance defect by creating a
     smaller one.

   **The two arguments this point originally rested on are both dead, and are recorded here so
   nobody reconstructs them.** It claimed to pay for itself by removing one of two `queueStore` pins
   named in `docs/REMOVING-THE-WEB-PLAYER.md`; that file, `queueStore.ts`, `playerStore` and
   `FullPlayer.tsx` are all deleted, so there is no pin to remove and that document is stale start to
   finish. It also claimed `ADR-0067` and `ADR-0068` would "re-expand" if the web visualizer stayed;
   both are now `rejected — superseded before acceptance`, so neither can.

10. **`docs/WEB-PARITY.md` gains a music video row, and it reads `❌ | ✅ | ❌`.** The file has no row
    for this feature at all today, which is how something with five endpoints came to have its
    reachability never discussed. The phone column is honest and it is a **loss**:
    `App/Shared/FullPlayerView.swift`'s `visualizerChoices` is not inside an `#if os(macOS)`, so
    `VisualizerChoice.musicVideo` is on the iPhone and point 9 removes it.

    **The loss is nominal, and the row's Notes cell must say so.** As drafted this point described
    removing a working capability; since `c00d99f` the phone's picker entry selects an id nothing
    serves, so what is actually being removed is a dead menu row. Claiming otherwise would put a
    false regression in the parity record.

    **The exclusion reasoning this point originally carried no longer applies to anything.** It
    argued that a ❌ in the Web column triggers `ADR-0060` point 1's second rule and so keeps the row
    out of the player's removal countdown without needing point 3's ADR. That reading is correct, and
    it is now moot: the countdown emptied and the fallback player was deleted on 2026-08-18
    (`WEB-PARITY.md:160`). Nothing turns on whether this row joins it. **Note also that the Listening
    table's whole Web column is stale** after `familiar` #190 removed browser playback — so the row
    should be added with its Notes cell explaining that the browser copy was deleted in `c00d99f`,
    not with the boilerplate about what the browser does not provide.

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
desynchronises it permanently, and the PWA's own implementation showed the correction is the cheap
part — `MusicVideo.tsx` did it in five lines with a 0.5 s threshold.

**Fix `MusicVideo.tsx` to read its `currentTime` prop and leave it a visualizer.** This was a real
option when the ADR was drafted — one line, and the Mac's existing picker entry starts syncing.
Rejected because working is not the same as being the right shape: a visualizer cannot own
fullscreen, cannot be a sidebar destination, and cannot carry the match-and-download action, which
together are the whole request. **It has since stopped being available at all**: the file was deleted
in `c00d99f`, so reinstating the visualizer would now mean authoring a new document under
`ADR-0087`'s format. That raises the cost of the cheap option to roughly the cost of this one, on a
shape already argued to be wrong.

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
- **Positive** — the last `music-video` strings in both repos go, so the hand-mirrored
  `VisualizerChoice` list stops naming something that does not exist. It will still be missing
  `spectrum`; that drift is real but is not this ADR's to fix.
- **Tradeoff** — sync is bounded by a 4 Hz playhead and will not be frame-accurate. Point 4 says so
  rather than implying otherwise.
- **Tradeoff** — **the phone ends up with no music video at all**, and the four replacement
  surfaces are Mac-only. As drafted this read as losing a working capability; it is not, because the
  phone's picker entry has selected nothing since `c00d99f`. What point 9 removes there is a dead
  menu row. The real tradeoff is the one that survives: a video downloaded on the Mac is watchable
  only there, and nothing on the phone will change that.
- **Tradeoff** — video files are large and `videos_path` is already in the S3 backup set
  (`backend/app/services/s3_backup.py:312`), so making videos easier to acquire makes backups grow.
- **Follow-up** — a host-time-anchored position on the audio engine, if point 4's bound proves too
  loose in use.
- **Follow-up** — whether `match_confirmed_by` on `track_videos` is written by point 7's action.
  `ADR-0086`'s own follow-up says the column should be removed if nothing claims it, and this action
  is its only plausible caller.
