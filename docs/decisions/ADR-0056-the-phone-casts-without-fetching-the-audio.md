# ADR-0056: The Phone Casts Without Fetching the Audio

Status: proposed

Date: 2026-08-16

Extends [ADR-0031](ADR-0031-casting-is-the-macs-and-excludes-zones.md), whose point 7 deferred
casting on the phone and named the bar for revisiting it. It does not reverse point 3: AirPlay stays
the operating system's job, and the in-app route picker that lands alongside this is that same OS
picker rendered inside the app rather than a second routing path.

## Context

ADR-0031 point 7 reads:

> **Casting is macOS-only initially.** The cost of point 5 is a full decode running silently for the
> length of a listening session, which on a phone is battery and an audio session held for output
> nobody hears — on the device most likely to be the thing you would AirPlay *from*. This does not
> reverse ADR-0013 point 2: casting is a listening feature, so the phone is eligible; it is deferred
> on cost, not on principle, and the ADR that revisits it should measure the drain rather than
> assume it.

Jeff asked for it on the phone. This is that ADR, and the first thing it has to say is that **the
cost point 7 names is probably not the cost that matters.**

### What casting actually does today

Read from `familiar-apple` at the time of writing:

- `Casting.swift:322` — `applyVolume?(isCasting ? 0 : Float(localVolume))`. The local engine keeps
  running, at volume zero, for the whole session.
- `Casting.swift:164` — `observe(_ player:)` subscribes to the player's `objectWillChange` (~4/sec)
  and reduces each change to a speaker command. **Nothing polls the device for position.** The local
  timeline is the only clock, and `CastSnapshot.trackEpoch` — a counter of track *starts* — is what
  tells the reducer to push the next track.
- The speaker fetches its own audio from the server through `device_stream_base_url`.

So a casting phone would pull **a second, complete copy of the audio over the network, decode it, and
discard it**, purely to learn when the track ends.

**The decode is the cheap half.** On a phone the expensive half is the radio: a continuous audio
stream over wifi or cellular for the length of a listening session, thrown away on arrival. Point 7
frames the cost as CPU and a held audio session. The stream is the larger number and the one that
scales with session length, and it is not mentioned.

### The option nobody considered

ADR-0031's alternatives rejected "adopt zones too", "AirPlay only", "fix the subsystem first",
"defer again", and "both platforms from the start". None of them considered **decoupling the
timeline from the decoder** — it is not a rejected option, it is an unexamined one.

The client needs exactly one fact from that discarded stream: when to advance. Two things make that
cheaper to obtain than it sounds:

- **Crossfade is already suppressed while casting** (ADR-0031 point 6), so sample-exact end-of-track
  is not required. The main reason to want a real decoder is already gone.
- The device already reports state, and point 8 already requires reading it back rather than
  trusting an optimistic local assumption.

### What this would cost, stated honestly

- **`PlayableTrack` has no duration.** It carries `id`, `streamURL`, `title`, `artist`, `album` and
  nothing else, so "the client already knows how long the track is" is **false** — that was claimed
  in conversation before the type was read, and it is wrong. Duration reaches the row menus
  (`durationSeconds`) but not the player's queue item. A timer-driven advance needs it added, and
  every construction site updated.
- A timer drifts, and a speaker paused or stalled at the device desyncs it. Correcting that needs a
  real status-polling loop, which does not exist today.
- The Mac would keep working either way, but leaving the two platforms on different timelines is the
  kind of divergence `docs/WEB-PARITY.md` exists to catch.

### What has not been done

**Nothing has been measured.** Point 7 requires it and this ADR does not satisfy that on its own.
Playback measurement on this project needs a person: the Mac app cannot be driven from tooling, and
`ps %cpu` reports a lifetime average that lies about a session. The protocol is in point 5 below,
and this ADR should not be accepted until it has been run.

## Decision

1. **Casting comes to the phone**, for `sonos`, `upnp` and `chromecast` — the same three ADR-0031
   point 4 adopted, and for the same reason: they are the devices the OS cannot route to. AirPlay
   remains the OS picker's job (point 3), now reachable from inside the app.

2. **The timeline is decoupled from the decoder.** A casting client does not open the audio stream
   at all. It advances on a timer seeded from the track's duration and corrected by polling the
   device, rather than by decoding audio it discards. This is the substance of the ADR; point 1
   without it is the thing point 7 declined.

3. **Both platforms move together.** The Mac adopts the same timeline, rather than the phone getting
   a second implementation. Two mechanisms for one behaviour is how the web and native drifted in
   the first place, and the reducer is already shared and already tested.

4. **Polling is a real loop, not an optimism.** The device is asked for its state on an interval
   while casting, and that answer corrects the timer. ADR-0031 point 8 already says a play that
   cannot be confirmed is reported as unconfirmed; this gives that rule something to read.

5. **This ADR is not accepted until the drain is measured**, because point 7 says so. The
   measurement, on a phone, cast to a real device, over at least twenty minutes:
   - battery percentage and Settings → Battery attribution before and after,
   - network bytes for the app across the session,
   - the same again with the decoupled timeline, on the same track list, same output, same volume.

   The number that decides it is bytes transferred, not CPU. If a casting session costs about what
   an idle app costs, point 7's concern is answered rather than argued with.

6. **`PlayableTrack` gains a duration**, since a timer cannot be seeded without one. Optional, so
   nothing that constructs a track today breaks, and a nil duration falls back to the current
   behaviour — decode locally — rather than failing to advance.

## Alternatives Considered

- **Ship phone casting exactly as the Mac does it, and accept the drain.** Simplest, and gets the
  feature to Jeff soonest. Rejected because it is the thing ADR-0031 point 7 already declined, and
  nothing has changed except that somebody asked for it. Asking is not new evidence.

- **Measure first, then decide the design.** The most defensible order, and close to what point 7
  literally asks. Rejected as the ordering rather than the substance: the measurement is worth more
  when there are two designs to compare, and point 5 above makes the comparison the measurement.

- **Keep the decode but drop the fetch — decode from a cached file.** Would help only for downloaded
  tracks, which is a minority of a library, and adds a branch where behaviour differs by whether a
  track happens to be on the device. Rejected as the worst kind of inconsistency: invisible until it
  matters.

- **Let the server own the cast timeline.** It knows the queue for the web client and could drive the
  device directly. Rejected because ADR-0028 made the Apple clients' playback session local, and the
  server holds no queue for them — this would reverse a decision far larger than this one to avoid a
  timer.

- **Do nothing; use AirPlay and accept that Chromecast and older Sonos are unreachable from the
  phone.** Honest, and it is the status quo. Rejected because those devices are precisely why the
  server subsystem exists, and the phone is the device most likely to be in the room with them.

## Consequences

- **Positive:** a casting phone stops paying for audio it discards, which is the cost that actually
  scales with session length.
- **Positive:** the Mac gets the same saving, and the two platforms keep one timeline.
- **Positive:** the polling loop point 4 requires is what makes point 8's "unconfirmed" state
  meaningful rather than aspirational.
- **Tradeoff:** a timer is less exact than a decoder. Crossfade is already off while casting, so the
  audible consequence is bounded, but a stalled device now desyncs until the next poll rather than
  never.
- **Tradeoff:** `PlayableTrack` grows a field, and every construction site has to be found. The
  optional-with-fallback shape in point 6 keeps that from being a flag day.
- **Follow-up:** `docs/WEB-PARITY.md` shows "Network output (Sonos/UPnP/Chromecast)" as
  `Web ✅ / Mac ✅ / iPhone ❌`. That row changes when this ships, and not before.
- **Follow-up:** if the measurement in point 5 shows the decoupled timeline saves little, this ADR
  should be rejected rather than watered down — the whole argument is that the saving is large.
