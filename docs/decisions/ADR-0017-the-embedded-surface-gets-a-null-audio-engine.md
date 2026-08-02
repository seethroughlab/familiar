# ADR-0017: The Embedded Surface Gets a Null Audio Engine

Status: proposed

Date: 2026-08-01

Extends [ADR-0016](ADR-0016-embedded-web-surfaces-on-the-mac.md).

## Context

[ADR-0016](ADR-0016-embedded-web-surfaces-on-the-mac.md) point 4 is the load-bearing rule of the whole
embedding decision: *"An embedded surface must never play audio… The embedded page runs browse-only,
and every play action is handed to the native `FamiliarPlayer`… **No second engine is ever
constructed.**"*

**That last sentence does not follow from the ones before it, and this ADR exists because the code
says so.** The reasoning was: a second engine is dangerous, playing audio is what constructs one,
therefore forbidding playback prevents construction. The middle step is false.

Traced on 2026-08-01:

| step | file | what actually happens |
|---|---|---|
| 1 | `packages/web/src/main.tsx:14` | `registerEngineFactory(() => new WebAudioEngine())` — stores a **closure**. Nothing is constructed. |
| 2 | `packages/frontend/src/player/audio/createEngine.ts` | `createEngine()` calls that closure, and **throws** if none was registered. |
| 3 | `packages/frontend/src/player/audio/engineInstance.ts:15` | `getEngine()` is a lazy singleton: `if (!engine) { engine = createEngine() }`. **This is the only construction site.** |

So construction is deferred to the first `getEngine()` — and `getEngine()` is not reached only by
playing. It backs seven exported helpers, and the ones that matter here answer *questions about
capabilities*, not commands to play:

```
areAudioEffectsAvailable()   isVisualizerAvailable()   getCurrentMode()
getAudioAnalyser()           getAudioContext()         getGlobalMasterGain()
getEngineOutputStream()
```

Every one calls `getEngine()` on the first line. Their existing callers are ordinary rendering code:

- `components/Settings/index.tsx:106` — `{areAudioEffectsAvailable() && <AudioEffectsSettings />}`
- `components/FullPlayer/FullPlayer.tsx:215,240,241,260` — four calls deciding what the player shows
- `components/Settings/DebugSettings.tsx:116–120` — five in one render
- `components/Settings/AudioEffectsSettings.tsx:133,136`

**A `WebAudioEngine`, and with it an `AudioContext`, is therefore constructed by a component asking
whether to draw a visualizer button.** No track is loaded and no sound is produced. A page obeying
point 4 to the letter — browse-only, every play intent posted to the native side — still ends up
holding the second engine that point 4 exists to prevent, and the failure is silent: two contexts
compete for the output device with nothing on screen to suggest why.

ADR-0016 named the remedy without knowing it was one. Its final Follow-up asks whether the embedded
page should be *"a purpose-built route that renders only Discover, rather than the full web app with
everything else hidden,"* noting the narrower route is "safer against point 4." It is more than
safer: it is the only version of point 4 that holds.

**But a narrow route alone is not enough either, and the same trace says why.** Registering nothing
does not make construction impossible — it makes `createEngine()` *throw* (step 2). A stray
capability check would then crash the page instead of constructing an engine, which trades a silent
failure for a loud one **inside a `WKWebView`**, where ADR-0016 already observes a defect "would be
far harder to diagnose." The engine must be absent in a way that answers questions rather than one
that raises.

For sizing: `AudioEngine` in `packages/frontend/src/player/audio/types.ts` declares 30 members —
**15 required and 15 optional** — so a complete null implementation is 15 no-ops and nothing else.

The web app is currently a single Vite entry — `packages/web/index.html`, with `vite.config.ts`
setting `rollupOptions.output` but no `input` — and the server serves it through one SPA fallback
that returns `static/index.html` for every non-API path (`backend/app/main.py:514–533`).

## Decision

1. **The embedded surface is a separate entry point that registers a null audio engine**, not the
   full web app with its chrome hidden. It is the narrow route ADR-0016's Follow-up describes, and
   the null engine is what makes it hold.

2. **The null engine implements `AudioEngine` completely and does nothing.** It reports
   `capabilities: { crossfade: false, visualizer: false, effects: 'none' }`, returns zeros and
   `null`s from its getters, and ignores every command. It omits all optional members. It never
   constructs an `AudioContext`.

3. **This replaces "must never play" as the mechanism, and keeps it as the intent.** ADR-0016 point 4
   is not reversed — the goal is unchanged and this ADR does not supersede it. What changes is that
   the guarantee stops depending on every current and future component avoiding a capability check,
   and starts depending on there being nothing to construct.

4. **A capability check on the embedded surface must answer, never throw.** Registering no factory is
   rejected for this reason, and so is throwing from the null engine's methods.

5. **The bridge still carries play intents to the native side**, exactly as ADR-0016 points 4 and 5
   describe. The null engine is a floor, not a replacement for the bridge: it guarantees that a
   *missed* intent is inert rather than a second engine.

6. **The ordinary web app is untouched.** It keeps `WebAudioEngine`, and nothing about this changes
   what a browser does. This is an additional entry point, not a change to the existing one.

7. **The null engine lives in `packages/web`**, beside `WebAudioEngine`, because it is a platform
   implementation of the same registration seam. `@familiar/frontend` gains nothing and keeps its
   rule of holding no engine.

## Alternatives Considered

**Register nothing on the embedded entry point.** The obvious reading of "no second engine is ever
constructed", and one line shorter than a null engine. Rejected on the trace above: `createEngine()`
throws when no factory is registered, so the first capability check takes down the page. Discover
would work until someone added a component that asked whether effects were available — and the crash
would surface inside a web view in a native app, which is the hardest place in the product to
diagnose anything.

**Keep the full web app and hide the chrome, as ADR-0016 point 2 first suggested.** No new entry
point, no build change, no server change, and Discover stays automatically current — which is the
main thing embedding buys. Rejected because hiding is not preventing: `FullPlayer.tsx` alone makes
four capability calls, and any of them constructs the engine whether or not the component is visible
to a user. It also leaves the guarantee dependent on every future change to a 2,943-line surface
remembering a rule enforced nowhere.

**Strip the capability calls out of the shared components instead.** Attacks the real cause — a
question about capabilities should not construct the thing it asks about — and would benefit the web
app too. Rejected as the wrong size for this: it is a refactor across Settings, FullPlayer and
DebugSettings, in service of a Mac feature, and it would leave the invariant resting on nobody
reintroducing the pattern. Worth doing on its own merits later; recorded as a Follow-up.

**Make `getEngine()` return a null engine whenever no factory is registered, in `@familiar/frontend`.**
Fixes it for every caller at once and needs no new entry point. Rejected because it makes a missing
registration *silently succeed* on every platform: the web app or the iOS app booting with a
registration bug would play nothing at all and report no error, and that is a considerably worse
failure than the throw that exists today. The throw is correct for the apps that should have an
engine.

**Give the embedded page a real `WebAudioEngine` and simply never call play.** No new engine type.
Rejected for the reason ADR-0016 rejected it outright: two engines in one process is the defect
ADR-0001 and `CarPlayBridge` are both written to avoid. Constructing one and promising not to use it
is the same object with a note attached.

## Consequences

- **Positive:** ADR-0016 point 4 becomes structural. The embedded page cannot construct a second
  engine, rather than being required not to.
- **Positive:** The failure mode of a mistake is inert rather than loud or silent — a missed play
  intent does nothing audible, instead of crashing a web view or opening a competing `AudioContext`.
- **Positive:** The embedded bundle is smaller, since it pulls in neither `WebAudioEngine` nor the
  effects chain.
- **Tradeoff:** A second entry point to keep working. `packages/web` currently has one
  (`index.html`, no `rollupOptions.input`), and the server has one SPA fallback serving
  `static/index.html` — both need to learn about the second, and the PWA plugin's precache will see
  it too.
- **Tradeoff:** Discover no longer stays current *entirely* for free. A change to how the app boots
  now has two entry points to pass through, which is a smaller version of the duplication ADR-0016
  rejected a native rebuild to avoid — but two `main.tsx` files rather than 26 components.
- **Tradeoff:** The null engine is code that exists to do nothing, and will look like dead code to
  anyone who finds it without this ADR. Its own comment should point here.
- **Follow-up:** Consider separating capability queries from engine construction in
  `engineInstance.ts`, so asking whether effects are available does not build an engine on any
  platform. That is the underlying defect; this ADR routes around it rather than fixing it.
- **Follow-up:** Decide what the embedded entry point renders beyond Discover, if anything. This ADR
  fixes how it boots, not what is on it.
