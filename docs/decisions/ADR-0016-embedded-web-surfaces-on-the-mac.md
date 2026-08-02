# ADR-0016: Embedded Web Surfaces on the Mac

Status: accepted

Date: 2026-08-01

Extends [ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md).

Implementation:
- Accepted 2026-08-01. One citation in the proposed draft was corrected against the repo before
  acceptance rather than after: Discover's **2,943 lines across 26 files** is right, but it is not
  all in `packages/frontend/src/components/Discovery/`. That directory holds 22 files and 2,458
  lines; the remaining 4 files and 485 lines are in
  `packages/frontend/src/components/Library/browsers/DiscoverBrowser/`. The size that decided
  point 2 is unchanged — the address was incomplete, not the measurement.
- The other figures were re-checked and hold: `VibeMap.tsx` is 690 lines,
  `library_maps.py` caps at 200 and 500 on lines 58 and 73, and `packages/web/src/main.tsx:14` is
  the unconditional `registerEngineFactory` call that point 4 exists to contain.
- Music Map first, being independent of the embedding half and much the lower risk of the two.

## Context

[ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md) puts Discover and Music Map on the Mac.
Both exist in the web app and both would be rebuilt in SwiftUI by default — but they are not the same
size of thing, and treating them the same would be a mistake in one direction or the other.

Measured on 2026-08-01:

| surface | size | renders with |
|---|---|---|
| Discover | **2,943 lines across 26 files** (`packages/frontend/src/components/Discovery/`) | ordinary React |
| Music Map | **690 lines in one file** (`…/Library/browsers/VibeMap/VibeMap.tsx`) | Canvas 2D |

Discover's row is two directories, not one, and the row above understated that: 22 files and 2,458
lines in `components/Discovery/`, plus 4 files and 485 lines in
`components/Library/browsers/DiscoverBrowser/`. Corrected here rather than quietly, because anyone
checking the figure would otherwise find 2,458 at the address given and conclude the ADR was wrong
about the size — when it is the split that was missing.

Discover is also the surface most likely to keep moving: it aggregates external sources, and its shape
follows what those sources make available. A native rebuild is a second implementation to change every
time the first one does.

**The performance question, answered.** The obvious argument for rebuilding the map natively is speed,
and it does not hold. `backend/app/api/routes/library_maps.py` caps the map at 200 entities and 500
maximum (lines 58 and 73). At 200–500 points nothing is near a GPU limit — Canvas 2D, SwiftUI `Canvas`,
SceneKit and Metal would all be idle between frames. SceneKit or Metal would buy nothing measurable.

What a native map *would* buy is different: no WKWebView resident in memory, real trackpad gestures
rather than emulated wheel events, and the ability to draw from cached data with no server. And
SwiftUI's `Canvas` (macOS 12+, iOS 15+) is a close analogue of the Canvas 2D drawing the web version
already does, so the rebuild is roughly the same 700 lines rather than a research project.

So the deciding axis is **churn and surface size**, not rendering. That reasoning generalises, and is
worth deciding once rather than re-arguing per feature.

**The constraint that governs any embedding.** `packages/web/src/main.tsx:14` calls
`registerEngineFactory(() => new WebAudioEngine())` unconditionally. A `WKWebView` running the web app
therefore stands ready to construct a second audio engine, and any play action inside it would: two
engines, two queues, two things holding an audio session. That is precisely the failure
`CarPlayBridge` exists to prevent — its own comment notes "two players would mean two queues, two
positions and two things holding the audio session" — and it would be far harder to diagnose arriving
from inside a web view.

## Decision

1. **Embed when a surface is large and moving; build native when it is small and settled.** The test
   is churn and size, not performance. A surface with many files that tracks external services is a
   poor candidate for a second implementation; a self-contained one that has found its shape is a
   good one.

2. **Discover is embedded** in a `WKWebView` pointed at the running server's web app.

3. **Music Map is built native**, drawn with SwiftUI `Canvas`, reading `/library/map` and
   `/library/map/ego` through the generated client — both carry the `library` tag and are already in
   the generated surface, so no schema work is needed. The two `*/stream` SSE variants stay outside it,
   per [ADR-0007](ADR-0007-clients-are-generated-from-openapi.md) point 8.

4. **An embedded surface must never play audio.** This is the load-bearing rule. The embedded page runs
   browse-only, and every play action is handed to the native `FamiliarPlayer` through a
   `WKScriptMessageHandler` bridge. No second engine is ever constructed.

5. **The bridge is one-way and narrow**: the page posts an intent — play these track ids, starting at
   this one — and the native side owns the queue, the playback and the reporting. The web view is
   never told what is playing and never renders a transport. One player, one queue, one now-playing
   entry, exactly as with CarPlay.

6. **The web view is given the server URL and profile explicitly** by the native app rather than
   relying on whatever the embedded app finds in its own storage, so it cannot end up pointed at a
   different server or acting as a different profile than the window around it.

7. **With no server reachable, an embedded surface shows a native "unavailable" state**, not a browser
   error page. Embedding is an implementation detail and should fail like the rest of the app.

8. **Embedding is a starting position, not a permanent one.** A surface that settles can be rebuilt
   native later; this ADR does not need superseding to do that, only the criterion in point 1 applied
   again.

## Alternatives Considered

**Rebuild Discover natively too.** Consistent, fully native, no web view in the app. Rejected on
maintenance: 26 files tracking external services is the part of the product most likely to change, and
a second implementation would have to change with it every time — the kind of duplication that is
quietly abandoned rather than deliberately removed.

**Embed the Music Map as well, for consistency.** Cheapest possible route for both, and one mechanism
instead of two. Rejected because the map is small, self-contained and finished, and the things a native
version gains — trackpad gestures, no resident web view, working from cached data — are exactly what an
interactive map is judged on. Consistency is not worth much when the two cases genuinely differ.

**Rebuild the map in SceneKit or Metal.** Considered because it was the first instinct, and measured
rather than assumed. Rejected: with the payload capped at 200–500 entities there is nothing for either
to accelerate, and both are substantially more machinery than SwiftUI `Canvas` for the same result.

**Let the embedded page play audio through its own `WebAudioEngine`.** Simplest bridge — no bridge at
all — and Discover would work exactly as it does in a browser. Rejected outright: two engines in one
process is the defect ADR-0001 and `CarPlayBridge` are both written to avoid, and it would produce two
queues and a contested audio session with the cause hidden inside a web view.

**Ship a menu item that opens Discover in the default browser.** Honest, trivial, no bridge and no
duplication. Rejected as not being the request: leaving the app is the friction ADR-0013 exists to
remove.

## Consequences

- **Positive:** Discover arrives at a fraction of the cost of a rebuild and stays current with the web
  version automatically, including changes made after this ships.
- **Positive:** Music Map is genuinely native where that matters — gestures, memory, and drawing from
  cached data with no server.
- **Positive:** There is now a stated test for the next feature like this, instead of an argument.
- **Tradeoff:** The Mac app contains a web view, and will look and feel like one on that screen —
  scrolling, text selection and focus will not match the rest of the app.
- **Tradeoff:** Embedded Discover needs the server reachable, so it is the one Mac surface with no
  offline story at all.
- **Tradeoff:** The bridge is a new seam between two clients that were previously independent, and a
  web-app change could break the native app through it. It should be narrow enough — one message
  shape — that this stays unlikely.
- **Follow-up, resolved by [ADR-0017](ADR-0017-the-embedded-surface-gets-a-null-audio-engine.md):**
  Decide whether the embedded page should be a purpose-built route that renders only Discover, rather
  than the full web app with everything else hidden. The narrower route is safer against point 4 but
  is a change in the web app. **Answer: the purpose-built route, and it registers a null audio
  engine.** Investigating this found that point 4's own conclusion did not hold — capability queries
  constructed an engine without playing anything, since fixed — and that Discover plays music itself,
  so an embedded copy has real play paths for the bridge to catch. ADR-0017 has both.
