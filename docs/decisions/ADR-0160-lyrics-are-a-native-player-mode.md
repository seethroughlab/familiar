# ADR-0160: Lyrics Are a Native Player Mode

Status: proposed

Date: 2026-11-06

Extends [ADR-0085](ADR-0085-music-videos-are-a-mac-function-not-a-visualizer.md) point 5.

## Context

Lyrics reached the listener as two visualizer documents, `lyrics` and `lyric-storm`. The listener's
report was that fetching "almost never works" and that the view is "super low FPS" on the phone.

**The first report had a different cause from the one it suggests.** Nothing was failing to match.
Nothing asked. `EmbedVisualizer.tsx:42` renders `AudioVisualizer` with no `lyrics`, `useSyncedLyrics`
has no callers outside its own test, and `VisualizerBundle.html` on `familiar-apple` `main` contains
`getLyrics` once, as its definition. ADR-0033 point 8's page-side fetch was never wired into the
embedded surface. Each document drew its "no synced lyrics" state over a field of the title's words,
which is what made it look like an occasional failure.

**The frame rate has not been measured.** Nobody can read it on the phone, because the debug panel's
switch is Mac-only. By reading the code, the likely contributors are a 3D word field that moves its
meshes on every sixth frame (`LyricWordField.tsx`) and three layers at `blur(70–90px)`
(`ScrollingLyrics.tsx:125-127`). With real lyrics flowing, the whole sheet would also re-render at
3–5 Hz.

The maintainer's decision: one lyrics view, simple, with no 3D, built natively.

A lyric line is text the listener reads, driven by a clock already on the native side. `Playhead`
covers the engine and the cast timeline, and publishes immediately on seek. Nothing about it needs a
web view, a sandbox or an audio frame.

## Decision

1. **Lyrics are a mode of the player, not a visualizer.** `PlayerBackdrop` gains `.lyrics`, alongside
   `.cover`, `.visualizer` and `.video`. ADR-0085 point 5's rule extends to it: one occupant of the
   player's background at a time.

2. **There is one lyrics view, on both platforms, and it is native.** SwiftUI text over a dark wash
   from the album art, the current line emphasised, a gentle scroll. No WebGL and no blur stack.

3. **The app fetches lyrics through the generated client.** `tracks_get_track_lyrics` is already
   generated. A native call has no CORS question and already carries the server token.

4. **The logic lives in FamiliarKit**, because `swift test` cannot see `App/Shared`. A pure cursor maps
   position to line and next wake time. No display link: lines are discrete, and the view publishes
   only when the line changes.

5. **Every state is truthful and distinct:** loading, synced, plain, instrumental, not found, cannot
   reach the service, and offline. "We could not ask" must never read as "this song has no lyrics".
   That confusion is what hid this defect.

6. **Results are kept on the device,** per server, excluded from backup and bounded, so a kept track
   has its lyrics offline. An answer that says nothing about the track is never cached.

7. **Prefetching happens only for profiles that have opened lyrics at least once.** A listener who
   never uses the feature should not send every play to a third party.

8. **Plain lyrics are shown too,** as a static scrolling sheet. Tapping a synced line seeks to it.

## Alternatives Considered

**Keep a lighter lyrics document.** Crisp text over a palette wash, with no WebGL, inside the existing
visualizer. It keeps one rendering path and lets plugin authors read a worked example. Rejected
because it still costs a web view, an iframe and a message hop to draw text, and the states in point
5 would each be built twice, once there and once in the app's own failure handling.

**Keep the 3D word field and optimise it.** Rejected by the maintainer: no 3D in any lyrics view. It
would also leave the frame rate limited by compositing that the design depends on.

**Fix the page-side fetch and stop there.** One prop on `EmbedVisualizer`, plus ADR-0164's origin and
token. It would make lyrics appear fastest. Rejected as the answer for lyrics, because it leaves the
frame-rate report untouched and leaves offline with no answer. ADR-0164 still does it, for plugins.

**Karaoke-style word timing.** Rejected for now. LRCLIB's data is line-level, so most tracks could not
use it.

## Consequences

- **Positive:** the listener gets lyrics that work offline, at native smoothness, and with honest
  states.
- **Positive:** lyrics stop depending on the visualizer's audio frames, so they work while casting.
- **Tradeoff:** the view is Swift-only. Plugin authors can still draw lyrics, under ADR-0164, but
  nothing first-party shows them how.
- **Tradeoff:** no `switch` over `PlayerBackdrop` is exhaustive, so a new case compiles and silently
  draws the cover. Each read has to be checked by hand.
- **Follow-up:** Bluetooth and AirPlay latency are unaddressed, so lines may lead the audio there. Add
  an offset only if it is visible.
- **Follow-up:** displaying third-party lyrics is new for App Review, and has not been assessed against
  the guidelines. Settle a position before 1.7 is submitted.
