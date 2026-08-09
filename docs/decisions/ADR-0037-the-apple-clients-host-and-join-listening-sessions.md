# ADR-0037: The Apple Clients Host and Join Listening Sessions

Status: rejected

Date: 2026-08-06

Extends [ADR-0036](ADR-0036-listening-sessions-signal-through-familiars-own-server.md) and
[ADR-0013](ADR-0013-the-mac-is-a-management-surface-too.md).

## Why This Was Rejected

**A Mac cannot host a listening session, and the whole decision rests on it being able to.** This
was found while building, on 2026-08-09, after points 2, 8 and 11 had shipped as a foundation — that
work is reverted and `familiar-apple` #90 is closed.

`RTCAudioDevice` is the only public route for feeding `AVAudioEngine`'s output into WebRTC, and
`stasel/WebRTC` **does not expose it in the macOS slice**:

- The header ships in `ios-arm64`, `ios-x86_64_arm64-simulator` and `ios-…-maccatalyst`. It is
  absent from `macos-x86_64_arm64`'s `Headers/`, its `Versions/A/Headers/`, and its umbrella header.
- macOS's `RTCPeerConnectionFactory.h` still declares
  `initWithEncoderFactory:decoderFactory:audioDevice:`, backed only by a forward
  `@protocol RTCAudioDevice;`. It compiles. Nothing can conform to it, so `nil` is the only argument
  available.

Without it, WebRTC uses its default audio device module, which captures **the microphone**. A Mac
host would stream the room rather than the music. That makes **point 4** — "a host adds one tap,
beside the analysis tap" — unachievable on macOS, and with it **point 1**.

**Precisely what does and does not work**, because the distinction is easy to lose: a Mac can
*join*. A guest's audio is played by WebRTC's own device, which is exactly what point 3 stops
`NativeAudioEngine` for, so the receive path never needed the custom device. iOS can both host and
join. **It is only the Mac's outbound path that has no route.**

The judgement, which is a product one rather than a technical one: a listening-party feature that
the machine holding the library cannot start is not worth a **44 MB** binary framework nobody here
can rebuild, shipped inside an App Store build. Point 2 asked for that liability to be entered
knowingly; knowing this, it is not entered.

Worth recording as an irony rather than a lesson: the Alternatives below reject *"Host only on the
Mac, join on both"*, and the binary forces close to the exact opposite.

Two things this rejection does **not** say. It is not a finding against libwebrtc — the string
`RTCAudioDeviceDelegate` appears in the macOS binary, so this reads as a packaging omission in the
distribution, and a build that exposed the protocol would remove the obstacle entirely. And it is
not a finding against listening sessions, which work in the web app against the listener's own
server under [ADR-0036](ADR-0036-listening-sessions-signal-through-familiars-own-server.md), and
which shipped.

**What would reopen this:** a maintained macOS WebRTC distribution that exposes `RTCAudioDevice`, or
a decision that iOS-only hosting is worth the dependency on its own. Either is a new ADR. The
material below is left exactly as it was proposed — the design was sound, and if the obstacle is
removed it is still the design.

## Context

[ADR-0036](ADR-0036-listening-sessions-signal-through-familiars-own-server.md) puts signalling back
on the Familiar server. This ADR decides what the Mac and the phone do with it.

**The embed/native test does not apply here, and that is worth stating once.** Every surface since
[ADR-0016](ADR-0016-embedded-web-surfaces-on-the-mac.md) has been weighed by churn and size, and
three have come out differently. This one cannot be weighed at all: ADR-0016 point 4 forbids an
embedded surface from playing audio, and a listening session *is* audio in both directions. The
answer is forced. Native, or not at all.

**This brings the first non-Apple dependency into `familiar-apple`.** `Package.swift` currently
declares three packages, all Apple's: `swift-openapi-generator`, `swift-openapi-runtime` and
`swift-openapi-urlsession`. There is no first-party WebRTC on any Apple platform, so a binary
distribution of libwebrtc is the only route. That is the substance of this decision more than the
feature is — the feature has been built once already, in TypeScript, and works.

**Two engine facts constrain the design, and both are recorded in the engine itself.**

The audio path is `AVAudioEngine` scheduling `AVAudioFile` buffers from files on disk, not a
streaming player. `NativeAudioEngine` holds two `AVAudioPlayerNode`s for crossfade, an EQ, a
reverb, a delay, a waveshaper, a compressor and a filter, and it plays *tracks the device has*. A
guest in a listening session receives a remote audio stream with no track, no file and no
`streamURL`. Nothing in that graph can accept one.

And the render path is closed on purpose.
[ADR-0024](ADR-0024-the-audio-engine-is-main-actor-except-where-it-cannot-be.md) point 3 made the
tap closure `@Sendable` and non-isolated after a Swift 6 runtime check crashed the app on the first
track played — `Thread 8 Crashed:: Dispatch queue: RealtimeMessenger.mServiceQueue`. The analysis
tap — at `NativeAudioEngine.swift:2408`, not 2148 as first written; the file has grown to 2,494
lines since — captures a processor and nothing else, and its comment says why in eleven lines. A
capture tap for a host's outbound stream would sit beside it under exactly the same rules.

**The web app's host path is one line of Web Audio.** `WebAudioEngine.getOutputStream()` lazily
branches `masterGain` into a `MediaStreamAudioDestinationNode` and hands the result to
`useWebRTCStreaming`. There is no native equivalent of that convenience; the same effect is a
second `installTap` and an encoder.

**ADR-0013 point 2 has to be addressed rather than routed around.** It says *"iOS stays the
listening path. The phone is not a management client."* Joining a session is plainly listening.
Hosting one is less obvious — but it edits nothing, configures nothing and administers nothing.
It starts a shared listen. On the wording of point 2, hosting is a listening act, and this ADR
takes it as one.

## Decision

1. **Both platforms host and join.** Hosting is not management under ADR-0013 point 2: it changes
   nothing about the library or the server, it starts a listen that other people can hear. Scoping
   hosting to the Mac was considered and is recorded below; the phone is where listening happens,
   and a listening party you can only start from a desk is a party in the wrong room.

2. **WebRTC arrives as a pinned SPM binary dependency**, and this is recorded as the repository's
   first non-Apple binary. It must be an exact-version pin rather than a range, it must be
   reviewable at the version pinned, and the exit is written down before it is added: if the
   package is abandoned, the feature is removed rather than the dependency forked. A binary
   framework nobody in this project can rebuild is a liability that should be entered knowingly.

3. **A guest does not play through `NativeAudioEngine`. The engine is stopped for the duration.**
   The peer connection owns the output while a guest is in a session, and the local player is
   stopped rather than paused-and-resumed-behind-the-scenes. Two things holding the audio session is
   the defect `CarPlayBridge` and ADR-0016 point 4 are both written to prevent, and a guest is the
   easiest place in the product to create one by accident.

4. **A host adds one tap, beside the analysis tap, and nothing else changes.** One engine, one
   queue, one now-playing entry. The capture closure is `@Sendable`, captures no `self`, and
   carries its invariant in a comment where it sits — ADR-0024 point 3's rules apply unchanged,
   because they were written for exactly this shape of code.

5. **A guest's listening produces no play events and no scrobbles.** The tracks are the host's;
   the guest's server has no ids for them and no reason to believe they were listened to by this
   profile. [ADR-0004](ADR-0004-listening-feedback-is-event-sourced.md)'s events and
   [ADR-0030](ADR-0030-scrobbling-is-the-servers-job.md)'s scrobbles both come from the host's
   playback, as they already do. Feeding a guest's stream into the ranking engine would poison it
   with someone else's taste.

6. **A guest's queue is the host's, and this is the one exception to
   [ADR-0028](ADR-0028-the-apple-clients-playback-session-is-local.md).** That ADR made the local
   session authoritative in both directions; for the length of a session as guest, it is not. The
   guest's own queue is preserved untouched and restored on leaving. Naming this as an exception is
   the point — it is the kind of thing that otherwise gets discovered when someone's queue
   disappears.

7. **Chat and reactions are native.** `SessionPanel.tsx` is 366 lines with a settled shape — join
   by code, host crown, kick, share link, a 500-character message cap and four reaction kinds — and
   it sits on the native side of ADR-0016 point 1 by the same measurement that put chat there in
   [ADR-0022](ADR-0022-chat-is-built-native-and-hidden-without-a-provider.md). It could not be
   embedded in any case, being attached to a surface that plays audio.

8. **The connection state machine lives in `FamiliarKit`, not in a view.** `swift test` cannot see
   `App/`, and this is the most stateful thing that will ever be in this app: handshake timeouts,
   ten reconnect attempts, pending sends, host departure, kick, and ICE failure. `App/` holds the
   translation, as it does for everything else with a decision in it.

9. **A session that cannot connect fails visibly, with its reason.** ADR-0036 point 7 on the phone
   and the Mac too. Behind symmetric NAT with no TURN configured this will happen, and a spinner
   that never resolves is the failure mode this project has now shipped three times.

10. **Interruptions are peer-visible.** `AVAudioSession` interruption handling already exists in the
    engine and compiles out on macOS. A host who takes a call, and a guest whose app is
    backgrounded, are states the other side is told about rather than left to infer from silence.

11. **The destination is absent when the server has no sessions endpoint**, read from the
    generated `sessions` surface. This is ADR-0022 point 3 applied a third time: not a disabled
    row, not an error after the user has typed a code. An Apple client pointed at a server built
    before ADR-0036 must not offer this at all.

## Alternatives Considered

**Join only; hosting stays web-only.** Genuinely the narrower and safer half: no capture tap, no
encoder, no host UI, and it sits more comfortably beside ADR-0013 point 2. It was the alternative
seriously weighed against point 1. Rejected because a guest-only client is a client that can never
start anything, and the person most likely to want a listening party is the person with the
library — who is increasingly on the Mac or the phone rather than in a browser.

**Host only on the Mac, join on both.** Splits the difference and maps cleanly onto ADR-0013's
division. Rejected on the reading of point 2 in the Context: hosting administers nothing, so the
management/listening line does not actually fall between hosting and joining. Drawing it there
would be borrowing a rule's authority for a distinction it does not make.

**Put a guest in a `WKWebView` pointed at the web app's guest page**, which already exists in
shelved form as `GuestListener.tsx`. No WebRTC dependency at all, and the hardest part — the
receive path — is already written. Rejected outright by ADR-0016 point 4: it is a web view playing
audio, which is the one thing embedding is never allowed to do, and it would construct the second
engine [ADR-0017](ADR-0017-the-embedded-surface-gets-a-null-audio-engine.md) exists to make
impossible.

**Use the existing casting path from [ADR-0031](ADR-0031-casting-is-the-macs-and-excludes-zones.md)
instead of WebRTC.** No new dependency, and the Mac can already send audio somewhere else.
Rejected because casting is same-network output routing to a device, and this is remote
co-listening with people. Different discovery, different transport, different failure modes, and
ADR-0031 deliberately excluded zones for reasons that would apply doubly here.

**Stream the host's *queue* rather than the host's *audio*, and have each guest play their own copy
from their own library.** Elegant for anyone who has the same tracks: no media path at all, no
WebRTC, just a synchronised cursor over track ids. Rejected because it only works between two
people with the same library, which is not what a listening party is — and the moment one guest is
missing a track, the feature silently becomes something else.

**Do not build this on the Apple clients.** The web app works and is a browser tab away, and this
is the largest and riskiest item proposed. Rejected because it was asked for, and because the whole
point of ADR-0001 was that listening moves to the native clients — leaving the social half behind in
the browser splits the feature across two apps.

## Consequences

**None of these came to pass — the decision was rejected.** They are kept as written because they
are the terms on which it would be reconsidered, and the second Tradeoff below is most of why it
was not.

- **Positive:** The Mac and the phone can start and join a listening session, on a server they are
  already configured against, with the profile they already hold.
- **Positive:** Point 3's rule means the guest path cannot produce two things holding the audio
  session, which is the failure this would otherwise have shipped.
- **Positive:** Point 5 keeps someone else's listening out of the ranking engine, which
  [ADR-0005](ADR-0005-one-ranking-engine-serves-ambient-and-radio.md) and ADR-0004 both depend on
  being honest.
- **Tradeoff:** **A binary framework enters the build that nobody here can rebuild or audit
  meaningfully.** Point 2 makes the terms explicit, but the exposure is real and permanent for as
  long as the feature exists.
- **Tradeoff:** Point 6 puts a hole in ADR-0028's "the playback session is local, in both
  directions". It is narrow and bounded by the length of a session, but it is the first one.
- **Tradeoff:** The engine gains a second tap and a stop-for-guest path, in a file whose complexity
  is already the subject of two ADRs.
- **Tradeoff:** Listening sessions are the only feature in the Apple clients with no offline
  behaviour at all — worse than embedded Discover, which at least fails on one screen.
- **Follow-up:** The share link a host produces has to open something. On Apple that suggests a
  universal link into the app and a web fallback, and neither exists — ADR-0036's follow-up about
  `/listen/{code}` is the other half of it.
- **Follow-up:** CarPlay. A guest in a session while driving is coherent and completely unspecified;
  `CarPlayBridge`'s one-player rule is the constraint that would govern it.
- **Follow-up:** Whether a host can be a guest of themselves across two devices — the phone joining
  the Mac's session on one profile — is undefined, and the profile-keyed local session makes it
  plausible enough that someone will try it.
