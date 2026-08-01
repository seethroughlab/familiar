# ADR-0015: Audio Effects Are Exposed, Not Rebuilt

Status: proposed

Date: 2026-08-01

Extends [ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md).

## Context

The web app has ten audio effects in `packages/web/src/audioEffects/effects/` — EQ, compressor,
reverb, delay, filter, stereo width, saturation, bitcrusher, chorus and tremolo — built on Web Audio
nodes and driven by `packages/frontend/src/components/Settings/AudioEffectsSettings.tsx`. The Mac app
appears to have none.

It has five. `NativeAudioEngine` holds `AVAudioUnitEQ`, `AVAudioUnitReverb`, `AVAudioUnitDelay`, an
`AVAudioUnitEffect` compressor and the custom `WaveshaperAudioUnit`, and exposes them through methods
that are already public:

| effect | entry point | line |
|---|---|---|
| EQ | `setEQ(lowGain:midGain:highGain:…)` | 1042 |
| reverb | `setReverb(preset:wetDryMix:enabled:preDelay:)` | 1062 |
| delay | `setDelay(time:feedback:wetDryMix:enabled:pingPong:)` | 1090 |
| compressor | `setCompressor(threshold:ratio:attack:release:…)` | 1119 |
| filter | `setFilter(highpassFreq:lowpassFreq:…)` | 1151 |

They arrived with the engine under [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md)
point 2 — "all 1,860 lines… move intact" — and nothing has ever called them. This is shipped,
previously-exercised DSP with no user interface in front of it. The Capacitor app drove these same
methods across the JS bridge; the bridge was deleted, and the methods were left behind it.

That reframes the work. "Audio effects on the Mac" sounds like a DSP project and is a settings screen.

The five the web has and the engine does not — stereo width, saturation, bitcrusher, chorus, tremolo —
are a genuinely different proposition. Each would be a new node on the real-time render path, in an
engine whose `Package.swift` records that Swift 6 strict concurrency already rejects it because of
"non-Sendable captures in the artwork fetch and the render callbacks", and where the render thread
"has real isolation requirements that `@MainActor`-by-default would get wrong".

Where the settings live is also already decided by precedent: `audioEffectsStore.ts` is a Zustand
store with no backend endpoint anywhere — `rg 'audio_effects' backend/app` returns nothing. Effect
settings have never been server state.

## Decision

1. **Expose the five effects the engine already has** — EQ, reverb, delay, compressor, filter —
   through a settings surface in the Mac app, calling the existing public methods.

2. **No new DSP, and the render path is not touched.** This adds no nodes to the audio graph and
   changes no code inside `NativeAudioEngine`'s processing. If exposing an effect appears to require
   engine changes, that is a signal to stop and reconsider, not to proceed.

3. **Stereo width, saturation, bitcrusher, chorus and tremolo are deferred**, and deliberately so.
   They are five new real-time nodes in an engine that is explicitly not yet Swift 6 concurrency-clean,
   for effects whose absence is not what prompted this. Anyone adding them should treat it as its own
   decision with its own ADR.

4. **Settings stay client-local**, as they are on the web. The Mac keeps its own effect settings in
   `UserDefaults`; they are not synced, and no server endpoint is added.

5. **Cross-client effect sync is a non-goal.** Effects are a property of *this speaker, in this room*,
   not of a listener's account. A profile whose EQ follows it from a laptop to a phone to a car would
   be actively wrong more often than right.

6. **macOS only**, per ADR-0013 point 2. The engine is shared with iOS and the methods are callable
   there, but no iOS surface is added.

## Alternatives Considered

**Match the web's ten effects.** True parity, and the shape a "bring audio effects to the Mac" request
most obviously implies. Rejected as a poor trade: five of the ten are already free, and the other five
cost new real-time audio code in an engine with known concurrency debt. If the missing five turn out
to matter in use, they can be added knowing exactly what they cost.

**Sync effect settings through the server so all clients agree.** Rejected on the merits rather than
cost. Effects compensate for output — headphones, car speakers, a desk monitor — so identical settings
across devices is the wrong default, and it would mean inventing server state for something that has
never had any.

**Reimplement the web's effects chain in Swift as a port of `EffectsChain.ts`.** Symmetrical, and
would make the two clients sound identical. Rejected because the engine's nodes are AVFoundation and
the web's are Web Audio; matching them is approximation, not porting, and the result would be two
implementations that sound *nearly* the same — which is worse than two that plainly differ.

**Put effects behind the existing web settings and skip the Mac entirely.** The status quo. Rejected
because effects belong to whichever engine is producing sound: the web's settings cannot alter what
the native engine is playing, so a listener on the Mac app has no way to reach them at all.

## Consequences

- **Positive:** Five effects arrive for the cost of a settings screen, on DSP that has already shipped
  and been exercised in the Capacitor app.
- **Positive:** The engine's real-time path is untouched, so this cannot regress playback — the class
  of bug that is hardest to find and worst to ship.
- **Positive:** It closes an odd gap where the Mac app's engine could do something no part of the app
  could ask it to.
- **Tradeoff:** The Mac and the web will not sound identical, and five effects exist in one client
  only. Named here so it reads as a decision rather than an omission.
- **Tradeoff:** Settings do not follow a listener between clients. Intended — see point 5.
- **Follow-up:** If the deferred five are wanted, they need their own ADR covering the render-thread
  and Swift 6 concurrency questions the engine's `Package.swift` already flags.
