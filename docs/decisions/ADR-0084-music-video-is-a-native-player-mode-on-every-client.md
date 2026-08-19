# ADR-0084: Music Video Is a Native Player Mode on Every Client

Status: proposed

Date: 2026-08-18

Extends [ADR-0066](ADR-0066-music-video-is-a-player-mode-not-a-visualizer.md) by answering its
point 4, which poses the question and deliberately leaves it open.

## Context

`ADR-0066` makes music video a third player background and removes `music-video` from the visualizer
registry. Its point 4 states the consequence it does not resolve: *"It is a mode on every client, or
it is browser-only and says so."*

**That question is load-bearing, because today the feature reaches the Apple clients only by riding
inside the visualizer bundle.** `MusicVideo` is a registered visualizer, so it is compiled into
`familiar-apple/App/Shared/VisualizerBundle.html` along with an inlined client for all five
endpoints — `/videos/{id}/search`, `/status`, `/download`, `/stream` and `DELETE /videos/{id}`. The
`videos` tag is **not** in the generated Swift surface, and nothing native calls those endpoints. The
native player has no video mode.

So `ADR-0066` executed on its own **deletes music video from the Mac and the phone**, silently:
the embedded page stops offering it, nothing native replaces it, and no test anywhere covers the
embedded surfaces. That is the failure shape this codebase keeps producing — `familiar` #70, #74 and
#76 — arriving through a decision rather than through a missed wire.

**The web implementation's shape is the design constraint, and it is already correct.** The
`<video>` element is `muted` (`MusicVideo.tsx:138`) and slaved to the audio playhead: it seeks when
it drifts more than half a second, and plays or pauses to follow `isPlaying`
(`MusicVideo.tsx:86-93`). **The audio always comes from the library track; the video is a silent
picture surface.** A music video carries its own audio — a different master, often a different edit —
and letting it sound would be two audio sources at once, which is exactly what `ADR-0016` point 4
forbids on the surface where it matters most.

**Downloading is server-side and has nothing to do with the offline stack.** The client searches,
posts a chosen URL to `/videos/{id}/download`, the server fetches and stores the file, and the client
streams it back. It never touched Dexie, `offlineService` or `downloadStore`, so `ADR-0071` does not
affect it.

**`docs/WEB-PARITY.md` has no row for music videos at all** — which is how a feature with five
endpoints and a native reach nobody had checked went undiscussed.

## Decision

1. **Music video is a background mode on all three clients**, and on the Apple clients it is rendered
   **natively**, not in a web view. `ADR-0016` point 1's test is churn and size: the web component is
   under 300 lines and has been stable, which is the "small and settled" side of that rule.

2. **The video is muted and slaved to the player's clock, on every client.** It is a picture surface
   and never an audio source. This is `ADR-0016` point 4 applied to the one feature that ships its
   own audio track, and it is the property most likely to be lost in a native rewrite, because an
   `AVPlayer` handed a video file will happily play its sound.

3. **The `videos` tag joins the generated surface.** It is added to `filter.tags` in the generator
   config and to `VENDORED_TAGS` in `lint_openapi.py` in the same change, per `ADR-0014` point 4, and
   the schema copy is verified under `ADR-0078` before the Swift side builds against it.

4. **The five endpoints are typed to `ADR-0007`'s standard before they generate**, not allowlisted
   after. In particular `/videos/{id}/stream` returns video and must say so — `ADR-0007` point 3's
   rule that a schema misdescribing an endpoint is worse than one leaving it untyped. This is
   `ADR-0014` point 6's precedent: when widening the surface exposed a bare `dict`, the backend was
   corrected rather than the lint relaxed.

5. **Downloading does not change.** The Apple clients call the same five endpoints; the server still
   fetches and stores the video. No background `URLSession` transfer, no local video store, no
   second mechanism. The thing that works keeps working the way it works.

6. **`docs/WEB-PARITY.md` gains a music video row**, as `ADR-0066` point 4 requires.

7. **`ADR-0066` must not land before this work ships, and the reason is the player's removal
   trigger.** The honest row *today* is ✅ ✅ ✅ — music video works on all three clients, embedded
   though the Apple path is. `ADR-0066` alone would make it ✅ ❌ ❌, and `ADR-0060` point 5 says a row
   added to the Listening table joins the countdown unless it is excluded. That would **re-open the
   countdown and un-meet `ADR-0058` point 4's condition**, blocking the web player's removal on a gap
   this decision created. The two ship together, or `ADR-0066` waits.

## Alternatives Considered

**Keep it embedded, on a fourth entry point of its own** — `video.html` beside `embed.html` and
`visualizer.html`. This reuses every line of working code and the whole download path, and it was the
strongest competitor. Rejected under `ADR-0016` point 1: the component is small and settled, which is
the native side of that test, and a fourth embedded document would need the playhead pushed to it,
making a second consumer of `ADR-0033`'s return channel for a feature that could simply read the
native player's clock directly.

**Browser-only, and say so.** Cheapest, and honest in the sense that it records a decision rather
than leaving a gap. Rejected because it removes a working capability from the two clients actually
used for listening, and does so at the moment the browser that would keep it is being deleted. It
would also need its own ADR under `ADR-0060` point 3 to become an exclusion, and neither exclusion
rule fits: it is not web-only by decision, and it is not absent everywhere.

**Let the native video carry its own audio and pause the library track while it plays.** Rejected
twice over: it is two audio sources under `ADR-0016` point 4, and it silently substitutes a different
master and often a different edit for the track the listener chose. The web implementation muting the
element is not an incidental detail; it is the feature working correctly.

**Leave `music-video` in the visualizer registry so the embedded path keeps working.** That is
`ADR-0066`'s decision and is not re-litigated here. It is worth recording that it would avoid this
entire ADR — and that its cost is the one `ADR-0066` names, a public plugin API forced to expose
`playerStore` and an HTTP client for a single entry that is not a visualizer.

## Consequences

- **Positive** — the feature survives `ADR-0066` on the clients it is actually used on, and gains a
  real affordance on all three instead of hiding in a menu of scenes.
- **Positive** — five endpoints stop being reachable only through a compiled-in copy of a web client
  vendored by hand into another repository.
- **Positive** — point 7 turns a silent regression into a sequencing constraint that can be checked
  by reading one file.
- **Tradeoff** — this is a coordinated cross-repo change: the `videos` tag joins the generated
  surface, the five endpoints need typing first, and the Apple clients need new native UI on two
  platforms. It is materially more work than `ADR-0066` alone implies.
- **Tradeoff** — syncing an `AVPlayer` to an external clock is fiddly, and the web heuristic — reseek
  past 0.5s of drift — is tuned for `<video>` in a browser. It is a starting point, not a
  specification.
- **Tradeoff** — `ADR-0066` point 6 says "nothing about the backend changes". This does not move or
  rename an endpoint, but it does change the generated surface and the typing of five operations, so
  that point is narrowed rather than contradicted.
- **Follow-up** — whether music videos become a destination of their own is still open, exactly as
  `ADR-0066` left it. Five endpoints with one affordance is the imbalance that usually means yes.
- **Follow-up** — the native control has to offer three background states from a press/hold gesture
  that today offers two, and a stored `showsVisualizer: true` must migrate to mean "visualizer"
  rather than "video". Both are `ADR-0066`'s tradeoffs and both land in this work.
