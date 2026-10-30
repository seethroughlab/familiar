# ADR-0157: The Recap Video Is Rendered on the Client

Status: accepted

Date: 2026-10-30

Implementation:
- **Accepted 2026-10-30.** Not yet built. It waits on ADR-0156's endpoint reaching `familiar-apple`
  through `scripts/vendor-schema.sh --fetch`.

Extends [ADR-0156](ADR-0156-a-recap-is-a-summary-of-a-window-of-play-events.md)

## Context

ADR-0156 gives every client a recap: the numbers. The listener wants something to post, and the
format that travels on Instagram Stories, TikTok and Reels is a short vertical video (1080×1920,
9:16) with music.

Nothing in either repository renders or shares video today. As of `familiar-apple` `beb78b7`,
`App/` and `Sources/` contain no `ShareLink`, `UIActivityViewController` or `AVAssetWriter`. The only
`AVAssetWriter` is a test helper that writes an audio fixture
(`Tests/FamiliarKitTests/AVFixture.swift`). The server runs ffmpeg for transcodes and mixtapes
(`backend/app/services/flac_remux.py`, `mixtape_export.py`) and Pillow for generated art
(`generative_art.py`), but it does not render frames.

The listener chose two things while this was planned:
- The video can be made from **whichever app they are using, on the Mac or on the phone**. The phone is
  the listening path (ADR-0013 point 2), and the Mac plays too.
- It carries **a clip of their #1 track**, cut from their own file.

## Decision

1. **The video is made on the device, in FamiliarKit, and the same code serves the Mac and the phone.**
   Frames are drawn with Core Graphics and CoreText into a `CGContext` and encoded with
   `AVAssetWriter` (H.264, 1080×1920, 30 fps, about 30 s). Every one of these APIs exists on iOS 17
   and macOS 14, the current floors.

2. **Frames are drawn with Core Graphics, never with `ImageRenderer` or `UIGraphicsImageRenderer`.**
   `App/Shared/AmbientSessionArtwork.swift` records that `ImageRenderer` returns blank images outside
   a layout pass, and a render loop is outside one. `UIGraphicsImageRenderer` does not exist on macOS.
   A slide is a pure function of the recap and a time *t*. The in-app preview draws the same function
   in a SwiftUI `Canvas`, so the preview and the export cannot disagree.

3. **The soundtrack is about 30 s of the #1 track, taken from the listener's own file.** A kept
   download is used if one exists. Otherwise the clip is fetched with
   `/tracks/{id}/stream?format=aac` (ADR-0118), which serves a lossy source untouched and encodes a
   lossless one once. The clip starts at about 30% of the track, with 1 s fades in and out.

4. **Sharing is the system's: `ShareLink` with the file's URL.** That is the share sheet on iOS and
   the sharing picker on macOS. Familiar posts nothing anywhere itself.

5. **The listener is told, once, that some apps mute copyrighted music.** That is the platforms'
   rule, not a defect. The note says they can add the song from the app's own library instead.

6. **The destination exists only when it has something to show:** from December 1 to January 31, and
   only when ADR-0156's `insufficient` is false. On the phone it is a row on the root list
   (ADR-0018). On the Mac it is a sidebar item. In both cases it is absent rather than disabled
   (ADR-0022 point 3).

## Alternatives Considered

- **Render on the server with Pillow frames and ffmpeg, as a background job modelled on mixtape
  export.** Rejected:
  - Encoding a 30 s 1080×1920 video is minutes of CPU on the NAS. ADR-0118 measured 12.4 s for a
    single audio transcode there, and the NAS is also the CI runner.
  - The listener would still download the result to the device to share it, so the server adds a
    round trip and saves nothing.
  - It would need a second, Pillow implementation of the slides, which would drift from the in-app preview.
- **Reuse a visualizer (ADR-0087) as the animated background, captured from a `WKWebView`.** Rejected:
  - Visualizers animate in real time on `requestAnimationFrame`, so they cannot be stepped frame by
    frame, rendered faster than real time, or reproduced exactly.
  - Capturing a web view means `takeSnapshot` in a loop, which nothing in the app does today.
  - A visualizer protocol message for a frame clock would be a real extension, and its own decision, if this is ever wanted.
- **Share a still image instead of a video.** Rejected as the main output: the listener asked for a
  video, and a story card with music is what gets posted. A still frame of any slide is easy to add
  later from the same drawing function.
- **Build it in the web app.** Rejected: the web app is an administration tool (ADR-0058 point 1), and
  a listener's recap is not administration.

## Consequences

- **Positive:** one renderer serves two platforms, and the preview is the export.
- **Positive:** the server's only new work is ADR-0156's query. No encoding load lands on the NAS.
- **Tradeoff:** an older phone takes noticeably long to encode. Show progress, and render once per tap
  rather than in the background.
- **Tradeoff:** audio may be muted when posted. Point 5 tells the listener, and nothing Familiar can do changes it.
- **Follow-up:** a still-image share of the "your sound" slide, and the 2027 recap, which is the first full year.
