# ADR-0161: Familiar Ships Two Visualizer Documents

Status: accepted

Date: 2026-11-06

Supersedes [ADR-0088](ADR-0088-every-visualizer-ships-as-a-document.md) point 1's "nothing is
dropped".

## Context

ADR-0088 point 1 ships `reactive-terrain`, `beat-tiles`, `lyrics`, `lyric-storm` and `spectrum`.

`spectrum` (4,897 bytes) draws the same FFT as the native meter in `FullPlayerView.swift`. On the
phone that meter is always in the controls, so choosing Spectrum shows two spectrums at once. The
native one is also the better of the two: log-spaced bars and a glide, against 64 linear samples and
a freeze on pause.

`lyrics` (1,233,544 bytes) and `lyric-storm` (1,224,930 bytes) are replaced by the native mode in
ADR-0160.

The picker has also never offered the plain album cover by name. `PlayerBackdrop.default` is already
`.cover` (`PlayerBackdrop.swift:22`), but it can only be reached by tapping the waveform glyph to
toggle, and every row in that menu turns a visualizer on (`FullPlayerView.swift:629`).

## Decision

1. **Familiar ships `beat-tiles` and `reactive-terrain`, and removes `spectrum`, `lyrics` and
   `lyric-storm`.**

2. **"Album Cover" is a named row in the picker,** first in the menu, and remains the default. The
   waveform glyph opens the menu rather than toggling. Only what is actually on screen is ticked.

3. **A profile's stored choice is migrated, not left to fall back.** A stored `lyrics` or `lyric-storm`
   with the visualizer showing becomes the lyrics mode. A stored `spectrum` becomes the cover. With
   Match to the Music on, the stored id was only a fallback, so the visualizer stays on and the id is
   cleared.

4. **A folder still in the user's directory stays selectable.** A copy the user edited is a plugin of
   theirs under ADR-0162, so these ids are **not** added to `RetiredVisualizers.ids`, whose rewrite
   would make it unreachable.

5. **`spectrum`'s document moves to `e2e/fixtures/vanilla-document/`,** because it is the only
   hand-written document the contract spec exercises.

## Alternatives Considered

**Rebuild Spectrum as something the meter is not, such as a scrolling spectrogram.** It would keep a
small hand-written example for plugin authors. Rejected by the maintainer in favour of removal: fewer
surfaces to bring up to a release standard, and the fixture in point 5 keeps the contract test.

**Keep Lyric Storm as the one 3D lyric surface.** Rejected by the maintainer: no 3D in any lyrics view,
and one lyrics view rather than two.

**Add the retired ids to `RetiredVisualizers.ids`.** The existing mechanism, and one line. Rejected
because it rewrites every stored id to the default, including for a user who kept an edited copy, and
because it would silently turn a Spectrum listener into a Beat Tiles listener.

## Consequences

- **Positive:** about 2.5 MB less in the bundle, and two documents to bring up to a release standard
  rather than five.
- **Tradeoff:** two visualizers is a short list. Match to the Music still has a real choice to make,
  since the two declare different affinities, but this makes it a smaller feature.
- **Tradeoff:** ADR-0064 point 4's and ADR-0103's counts of what ships are out of date from here.
- **Follow-up:** `site/visualizers.json`, `site/visualizers.html`, `render-docs.py` and
  `VISUALIZER_API.md` change in the same step, and `check-claims.py` compares the gallery with the
  bundle, so the two repos' removal PRs merge the same day.
