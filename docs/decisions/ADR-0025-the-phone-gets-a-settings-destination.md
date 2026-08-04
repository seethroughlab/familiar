# ADR-0025: The Phone Gets a Settings Destination

Status: proposed

Date: 2026-08-04

Extends [ADR-0015](ADR-0015-audio-effects-are-exposed-not-rebuilt.md) and
[ADR-0018](ADR-0018-the-phone-navigates-from-a-root-list.md).

## Context

**The phone has no settings screen at all.** Not a hidden one, not a thin one — none.
`SettingsWindow`, `EffectsSettingsView` and `QueueSyncSettingsView` are each wrapped in
`#if os(macOS)`, and they are mounted in a `Settings { }` scene, which is a macOS-only scene type.
The only configuration surface the phone has is `SetupView`, reachable when the app is not yet
connected to a server, offering a URL field and a profile list.

So on the phone today: the six audio effects cannot be reached, the queue-sync toggle cannot be
reached, and the server or profile cannot be changed once chosen without reinstalling.

**One of those exclusions is a decision and the rest are not.** ADR-0015 point 7 says
*"macOS only, per ADR-0013 point 2. The engine is shared with iOS and the methods are callable
there, but no iOS surface is added."* That is explicit and it is what this ADR reverses. Queue sync
was never scoped by any ADR — it is macOS-only because of an `#if`, which is the same thing ADR-0019
found for embedded Discover: implementation inherited from ADR-0013 point 3 scoping a body of *work*
to the Mac, rather than a decision about platforms.

**ADR-0015's own reasoning argues for the phone.** Point 6 keeps effects per-device because they are
"a property of *this speaker, in this room*, not of a listener's account", and the Alternatives
section says why: *"Effects compensate for output — headphones, car speakers, a desk monitor."* Two
of those three are phone contexts, and they are the two where compensation matters most — a desk
monitor is the one output you can fix by moving it. Point 7 excluded iOS on scoping grounds while
point 6 was making the case for including it.

ADR-0013 point 2 keeps *management surfaces* off the phone — pending review, proposed changes,
mixtapes, the library's editorial machinery. None of this is that. How loud the bass is and whether
downloads happen automatically are properties of listening, which is the thing the phone is for.

**A finding that is worth stating separately, because it is not a scoping question.**
`favorites_auto_download` is read at launch by both native apps — `LibraryView` calls
`favoritesGetFavoritesAutoDownload`, and silently queues whatever is missing. The setter,
`favoritesSetFavoritesAutoDownload`, is called **zero times** in the entire Apple codebase. **The
apps obey a setting they give you no way to change**; the only way to change it is the web app. That
is the same shape as ADR-0022's chat destination — a capability the server has and the client cannot
reach — and it is a gap on the Mac as much as the phone.

**The settings are not all the same kind of thing**, and mixing them without saying so is how a
listener gets surprised:

| setting | scope | where it lives |
|---|---|---|
| Effects | this device | `UserDefaults` (ADR-0015 point 5) |
| Queue sync | this device | `UserDefaults` |
| Favorites auto-download | **this profile, on the server** | `/favorites/auto-download` |
| Server and profile | this device | `UserDefaults` |

Three of the four are per-device. The fourth changes behaviour on every client the profile touches,
including the web app.

## Decision

1. **The phone gets a Settings destination in the root list.** ADR-0018 made the phone's root one
   list of destinations; Settings is a destination and belongs in that list rather than behind a gear
   in a toolbar, which would be a second navigation idiom for one screen.

2. **Effects come to the phone, reversing ADR-0015 point 7.** The same six the Mac exposes, from the
   same `AudioEffectSettings` and the same engine methods — ADR-0015 point 2's "exposed, not rebuilt"
   applies unchanged. ADR-0015 point 7 is reversed rather than reinterpreted: it named the platform,
   so this is a change of mind and is recorded as one.

3. **Effects stay per-device, and the phone is a different device.** ADR-0015 points 5 and 6 are
   untouched and now matter more: an EQ curve set for car speakers must not follow the listener to a
   desk. Nothing is synced and no server endpoint is added.

4. **The queue-sync toggle comes with it**, needing no reversal — nothing scoped it to macOS but an
   `#if`.

5. **Favorites auto-download gets a toggle, on both platforms.** A setting the app obeys and cannot
   change is a defect rather than a scope decision, and fixing it on the phone alone would leave the
   Mac in the same state. This is the one control here that writes to the server.

6. **Per-profile settings say so in the interface.** The auto-download toggle carries a line naming
   that it applies to this profile everywhere, not to this device. Three per-device settings and one
   per-profile setting in one list, undistinguished, is a trap — and the distinction is invisible
   from the control itself.

7. **Server and profile move into Settings, and `SetupView` keeps first run.** Connecting for the
   first time stays its own screen, because a listener with no server has nothing else to do and a
   settings list would bury the one action that matters. Changing server or profile afterwards
   belongs here.

8. **The two platforms share panes, not chrome.** The Mac keeps its `Settings` scene and ⌘, window;
   the phone gets a pushed list. Each pane is one view used by both, so a setting added later appears
   on both platforms unless someone deliberately excludes it — which is the failure mode this ADR
   exists to correct.

## Alternatives Considered

**Leave effects on the Mac, add only queue and downloads to the phone.** No ADR reversal needed, and
the smaller change. Rejected because it is the status quo's reasoning repeated: the phone is where
headphones and car speakers are, which is where the effects ADR itself says compensation matters.
Shipping a settings screen that deliberately omits the setting most worth having on that device
would need a better reason than "an earlier ADR said so".

**Put settings in the iOS Settings app via a settings bundle.** The platform-native answer for
configuration, and free of any in-app navigation question. Rejected because six effects with
continuous sliders and live audition are not a settings bundle — that surface is for static
preferences, cannot show the current signal path, and would put the controls in a different
application from the audio they affect.

**A gear button in the toolbar rather than a root-list row.** Familiar from most apps. Rejected by
ADR-0018 point 1: the phone's root is a list of destinations precisely so there is one way to reach
things, and a toolbar affordance for a single screen reintroduces the second idiom that ADR replaced.

**Sync effects across clients so the phone inherits the Mac's.** Rejected already by ADR-0015 point
6, and the reversal here strengthens rather than weakens it — the more devices with effects, the
more wrong a shared EQ becomes.

**Fix the auto-download toggle separately from this work.** Tempting, since it is a defect rather
than a feature and is not phone-specific. Rejected only on sequencing: the surface it belongs on is
the one being built, and adding it here costs a toggle where adding it first would cost a settings
screen on the Mac to hang it from.

## Consequences

- **Positive:** the phone becomes configurable at all. Today a listener who picks the wrong profile
  reinstalls the app.
- **Positive:** effects reach the device where output varies most — headphones on a train, a car
  stereo, a kitchen speaker — which is the case ADR-0015 made and then scoped away.
- **Positive:** `favorites_auto_download` becomes reachable on both platforms, closing a gap where
  the app obeyed a setting the listener could only change elsewhere.
- **Tradeoff:** four settings in one place with two different scopes. Point 6 mitigates it with
  wording, which is weaker than structure; the alternative was hiding the server-side one, which is
  how it got missed in the first place.
- **Tradeoff:** the phone's root list grows by one row. ADR-0018 point 5 accepted that reaching a
  destination costs a tap; this spends one of those taps on a screen most people open twice.
- **Follow-up:** whether the Mac's `Settings` window should gain the same Downloads pane structure
  rather than only the toggle, once there is more than one download setting to put in it.
- **Follow-up:** whether `SetupView` and the Settings server pane should share a view rather than
  agreeing by inspection. They validate the same URL and list the same profiles.
