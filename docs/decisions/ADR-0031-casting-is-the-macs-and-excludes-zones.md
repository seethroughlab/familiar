# ADR-0031: Casting Is the Mac's, and Excludes Zones

Status: proposed
Date: 2026-08-05

Extends [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md) and
[ADR-0014](ADR-0014-the-generated-surface-widens-to-management.md)

## Context

The Apple clients cannot send audio to a Sonos, a WiiM, or a Chromecast. `outputs` is the single
largest tag missing from the generated surface — **24 operations**, more than any other — and there
is no generic web view in the app to reach it through.

**ADR-0001 already litigated this, and deliberately left it open.** `outputs` was added to the
generated surface and removed the next day (2026-07-28, `ffb9251`), with the reason recorded there:

> Casting on the native client is a live question for whenever it enters scope, not a settled
> inclusion.

This ADR answers that question. Doing so required understanding the mechanism, and the mechanism is
not what the name suggests.

**"Playing to a Sonos" does not move playback off this device.** The server never proxies or
transcodes audio; it is a control plane. It hands the speaker a URL and the speaker opens its own
HTTP connection back to `GET /api/v1/tracks/{id}/stream` — which takes no profile dependency, and
that is what makes an unauthenticated device fetch possible at all. Meanwhile the client keeps
fetching, decoding and running the transport clock, and is simply **muted to zero**
(`useAudioEngine.ts:765-769`, *"Mute local output while casting to a network device (avoids double
audio); restore on return"*). Two concurrent fetches of the same track exist, and the muted local
engine remains the timeline authority: end-of-track, queue advance and the resulting push to the
device all originate from it.

**The subsystem is in worse repair than its endpoint count suggests.**

- **Nine of the twenty-four operations are zones, and zones are dead.** They have no client
  anywhere. Their state is in-memory and lost on restart — `_persist()` serializes outputs only and
  `load_persisted()` never reads zones. Fan-out loops members *sequentially*, awaiting each, so
  members start staggered by the sum of prior devices' connect latencies; this is not synchronised
  multi-room. And `GET /outputs/zones` is **unreachable**: it is registered at `:304`, after
  `GET /{output_id}` at `:212`, so Starlette matches `zones` as a UUID path parameter. Verified —
  it returns **422**, `path.output_id: Input should be a valid UUID … found 'z' at 1`.
- **There is no server-side notion of who is driving an output.** No outputs endpoint takes
  `X-Profile-ID`. The registry is a process-wide singleton, so devices, their transport state and
  their volume are shared by every profile and every client. Selection is the opposite: the web's
  `activeOutputId` has no persistence, so a reload silently returns to "This Device" while the
  speaker keeps playing.
- **Failures are invisible.** Every transport method swallows exceptions and returns `False`; every
  web call site is `.catch(() => {})`. There are no retries. Sonos never reconnects after
  construction — if `_connect()` failed at boot, every call returns `False` for the process's
  lifetime.
- **A play that reports success is not a play that made sound.** `device_stream_base_url` exists
  because the browser builds stream URLs from its own origin, which is meaningless to a speaker.
  Misconfigured, the device is handed a URL it cannot reach, the SOAP or CAST call is still
  acknowledged, and `play` returns `{"status": "playing"}` over silence.
- **Discovery mutates global state through a `GET`.** Every discover call auto-registers what it
  finds and rewrites `data/outputs.json` for everyone.

**A distinction the naming actively hides.** The `airplay` output type and the AirPlay button in the
app are unrelated mechanisms. `AirPlayButton.tsx:6-9` says so: the button *"presents the iOS system
route picker … independent of the backend-driven 'Play To' outputs"*. With the OS picker the client
remains the audio source and iOS re-routes already-decoded output; with the `airplay` output type
the speaker becomes the source and the client mutes itself. **Nothing prevents both being active at
once**, and the result is double audio, because the local engine is muted only by `activeOutputId`,
which the OS route picker never sets.

Finally, the device fetches drive additional concurrent long-lived requests against
`GET /tracks/{id}/stream` — the endpoint whose own comments record that it exhausted the connection
pool on 2026-08-02 with 2,416 `QueuePool limit` errors. That is fixed, but casting is the feature
that multiplies exactly that traffic.

## Decision

1. **The Apple clients adopt casting, narrowly, and the generated surface widens to `outputs`.**
   ADR-0001's open question is answered yes — casting is part of the listening path, and a client
   that cannot reach a Sonos is missing it.

2. **Zones are excluded from the generated surface and from the client.** Nine operations that no
   client calls, whose state does not survive a restart, whose fan-out is sequential rather than
   synchronised, and one of which is unreachable through a routing shadow. Generating them would
   produce Swift methods for an API that is partly broken and wholly unused. Fixing zones is a
   separate decision, on the server, before any client should depend on them.

3. **The `airplay` output type is excluded too, and the OS route picker is the answer instead.**
   Where the operating system can route audio, letting it do so is strictly better: the client stays
   the source, so there is no second fetch, no muted decode, no `device_stream_base_url` dependency
   and no LAN-reachability requirement — and the route survives as OS state that other apps and the
   system volume respect. This also removes the double-audio trap by construction, because the app
   never offers two ways to reach one speaker.

4. **What is adopted is therefore: list, discover, and single-output transport** — play, pause,
   resume, stop, seek, volume — **for `sonos`, `upnp` and `chromecast` only.** These are the devices
   the OS cannot route to. `browser` is excluded as well: it is a state stub that controls nothing,
   and its `websocket_id` field is never read by anything.

5. **The client remains the timeline authority, muted, exactly as the web client is.** The queue,
   end-of-track detection and the advance that pushes the next track to the device all keep running
   locally. This is not elegant and it is not optional: the server has no queue for the Apple
   clients to lean on (ADR-0028), so nothing else knows what plays next.

6. **Crossfade is suppressed while casting**, matching the web (`getEffectiveCrossfadeDuration`
   returns 0 when a network output is active) so a device plays each track to its true end. This
   constrains [ADR-0026](ADR-0026-crossfade-is-decided-by-the-player-not-the-engine.md) before it is
   built, and is recorded here so the two are not designed in ignorance of each other.

7. **Casting is macOS-only initially.** The cost of point 5 is a full decode running silently for
   the length of a listening session, which on a phone is battery and an audio session held for
   output nobody hears — on the device most likely to be the thing you would AirPlay *from*. This
   does not reverse ADR-0013 point 2: casting is a listening feature, so the phone is eligible; it
   is deferred on cost, not on principle, and the ADR that revisits it should measure the drain
   rather than assume it.

8. **A device is never assumed to be playing because a call succeeded.** The client shows state read
   back from the device via `get_status`, not the local optimistic assumption, precisely because the
   `device_stream_base_url` failure returns success over silence. A play that cannot be confirmed is
   reported as unconfirmed rather than shown as playing.

9. **Discovery is an explicit action, never automatic on opening a screen.** It rewrites global
   state shared by every profile, and takes up to ten seconds across four protocols. A listener asks
   for it.

10. **Verification is against real hardware, and the third layer is not optional.** URL construction
    and the type filtering in point 4 are pure and unit-tested in `FamiliarKit`; the transport
    calls extend the generated-client tests; and playback to an actual Sonos or WiiM is confirmed by
    hand, **including the `device_stream_base_url` failure**, because that is the one that reports
    success over silence and no automated test on this side can see it.

## Alternatives Considered

**Adopt the whole tag, zones included.** The simplest config change, and symmetrical with the web.
Rejected on measurement: nine of the twenty-four operations have no client, no persistence, and no
synchronisation, and one of them cannot be called at all. Generating a Swift method for
`GET /outputs/zones` would produce a call that always returns 422 — a defect shipped as an API.

**Rely on AirPlay alone and skip server-mediated outputs entirely.** Genuinely attractive: it needs
no schema, no LAN URL, no muted decode, and it is consistent with ADR-0028's local-session grain.
Some Sonos models even support AirPlay 2. Rejected because Chromecast does not, older Sonos and most
UPnP renderers do not, and those are exactly the devices the server subsystem exists to reach.
Point 3 keeps the AirPlay-first half of this argument where it applies.

**Fix the subsystem first — ownership, retries, error reporting — then adopt it.** The most
defensible sequencing, and what a stricter reading of the evidence argues for. Rejected as the
enemy of shipping anything: the reliability problems are real but they are *equally* real for the
web client today, and are not made worse by a second consumer. Points 8 and 9 mitigate the two that
would be actively misleading on a new surface. An ownership model is recorded as a follow-up rather
than made a precondition.

**Defer again, as ADR-0001 did.** Rejected because the question has now been examined rather than
postponed. If the answer were still "not yet", that should be written down as a decision with a
stated bar, not left as a third deferral.

**Put casting on both platforms from the start.** Rejected on cost, not principle — see point 7.
The muted-decode requirement is the whole reason, and it is a battery cost that wants measuring
before it is imposed on a phone.

## Consequences

- **Positive.** ADR-0001's open question is closed, in writing, with the mechanism understood rather
  than assumed.
- **Positive.** The Mac can play to the speakers in the house, which is a genuine part of the
  listening path that the web app has and the native client did not.
- **Positive.** Excluding zones and `airplay` keeps the generated surface at fifteen operations
  rather than twenty-four, and keeps the client away from the parts that are broken.
- **Positive.** Point 3 removes the double-audio failure by construction rather than by guarding
  against it.
- **Tradeoff.** The muted local decode is genuinely inelegant: the Mac fetches and decodes audio it
  will not play, for as long as casting lasts. It is the price of the client owning the queue, and
  it is the reason point 7 keeps this off the phone for now.
- **Tradeoff.** Two concurrent fetches of the same track hit `GET /tracks/{id}/stream`, the endpoint
  that exhausted the connection pool once already. The fix is in and the fetches are sequentialish
  rather than bulk, but casting is the feature that multiplies that traffic.
- **Tradeoff.** Adopting `outputs` will trip the OpenAPI linter: its five allowlisted untyped
  operations are all `outputs/zones/*`, so excluding zones from the *generated* surface must be
  expressed in the lint's scope too, or the allowlist grows to cover operations no client uses.
- **Follow-up.** **There is no server-side owner for an output.** Two clients can drive one speaker
  with neither aware of the other. This is pre-existing and the ADR does not fix it, but a second
  client makes it likelier to be met.
- **Follow-up.** `GET /outputs/zones` is unreachable behind `GET /{output_id}`. A one-line
  reordering fixes it, and should happen whether or not zones are ever used.
- **Follow-up.** `lint_openapi.py`'s `NOT_GENERATED` names `{"ambient", "outputs"}`, is **declared
  and never referenced**, and its docstring describes an exclusion set of two when twenty tags are
  excluded. Removing `outputs` from a constant nothing reads will not change any behaviour — which
  is the point, and the reason it should be made real. See ADR-0030's identical follow-up.
