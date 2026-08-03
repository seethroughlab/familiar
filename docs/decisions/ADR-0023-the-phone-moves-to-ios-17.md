# ADR-0023: The Phone Moves to iOS 17

Status: proposed
Date: 2026-08-03

Extends [ADR-0021](ADR-0021-track-lists-on-the-mac-are-sortable-tables.md)

## Context

[ADR-0021](ADR-0021-track-lists-on-the-mac-are-sortable-tables.md) point 2 moved the Mac to
macOS 14 and said plainly that **"iOS is untouched at 15"**, on the grounds that
[ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md)'s reasoning about not regressing the
Capacitor app's devices "applies to the phone, not to a Mac app that has never shipped to anyone."
Reversing that needs a decision of its own, which is this one.

**The prompt was small and the finding was not.** Building the chat surface on the phone
([ADR-0022](ADR-0022-chat-is-built-native-and-hidden-without-a-provider.md) point 7) ran into three
unavailable APIs and degraded the composer to a single line to avoid them. That looked like the whole
cost. It is not.

**The floor is why the phone has no swipe-back.** `LibraryView` holds
`@State private var path: [BrowseRoute]` (line 59) and drives it by hand: `path.append(…)` at ten
call sites, `path.popLast()` behind a custom `backBar` whose own comment says it "Stands in for a
navigation bar neither platform provides here" (line 493). There is no `NavigationLink` and no
`NavigationStack` anywhere in the app, because `NavigationStack(path:)` is iOS 16. The result on the
phone is a hand-rolled stack with a hand-drawn back button and **no interactive pop gesture** — the
single most-used navigation gesture on the platform, absent from a listening app whose whole job is
browsing. `LibraryView`'s header comment and `LibrarySidebar`'s both record the floor as the reason.

What else the floor currently costs, all of it verified in the tree at write time:

| Wanted | Available from | Worked around by |
|---|---|---|
| `NavigationStack(path:)` | iOS 16 | a hand-rolled `[BrowseRoute]` stack and `backBar` |
| `TextField(axis:)`, `lineLimit(1...6)` | iOS 16 | the phone's chat composer is one line |
| `onChange(of:initial:)` | iOS 17 | `followsStreamingText` in `ChatView`, plus 8 deprecated `onChange(of:perform:)` call sites |
| `AVAsset.load(_:)` | iOS 16 | `#available` in `Sources/FamiliarKit/Artwork.swift:122` |

**The device cost is nil.** The only paired device is an **iPhone 13 Pro** (`iPhone14,2`), which runs
current iOS; TestFlight distribution is to the author. ADR-0001's argument was about not regressing
devices the Capacitor app already served — a real concern then, and an empty one now that the
audience is one phone the author holds.

## Decision

1. **The iOS deployment target moves from 15 to 17**, in `Package.swift` and both
   `IPHONEOS_DEPLOYMENT_TARGET` entries in `Familiar.xcodeproj`. macOS stays at 14; the floor is per
   platform, as ADR-0021 point 2 established.

2. **17 rather than 16, because 16 is a partial fix.** 16 buys the two that matter most —
   `NavigationStack` and the composer — but leaves `followsStreamingText` and eight deprecated
   `onChange` call sites in place, which is a compatibility branch kept alive for one API. 17 clears
   every branch currently in the tree, and there is no device between the two to protect.

3. **Not higher than 17.** Nothing in the table above needs 18, and a floor is easier to raise again
   than to justify in advance. This ADR is the precedent for raising it when a named API earns it,
   not a licence to track the latest SDK.

4. **Adopting `NavigationStack` is separate work, not part of this decision.** This ADR makes it
   possible; it does not do it. Replacing a hand-rolled stack that ten call sites push onto is a
   change to how the phone navigates, with its own risk, and bundling it into a deployment-target
   bump would make both harder to review and to revert. The mechanical cleanups in the table —
   composer, `followsStreamingText`, the `onChange` sites, the `Artwork` guard — ship with the bump
   because they only remove code the bump makes dead.

5. **The floor is a floor, not a target.** Raising it does not oblige any surface to adopt a newer
   API; it removes the availability question. Existing code keeps working unchanged.

## Alternatives Considered

**Leave the floor at 15 and keep working around it.** The status quo, and defensible while the
workarounds were small. Rejected on what the survey turned up: the workaround is no longer a one-line
branch but the phone's entire navigation model, and the user-visible cost is a missing swipe-back
gesture rather than a slightly plainer composer. Continuing to pay it buys nothing — there is no
device on 15 or 16 to serve.

**Move to 16 rather than 17.** The conservative choice, and it delivers the two most valuable APIs.
Rejected because the remaining branch — `followsStreamingText` and eight deprecated `onChange` calls
— exists solely to span iOS 15/16 and macOS 14, and would survive a bump to 16 unchanged. Paying the
cost of a floor raise and keeping the compatibility code is the worst of both.

**Adopt `NavigationStack` in this same change.** Tempting, since it is the reason for the ADR.
Rejected as decision point 4 says: it is a navigation rewrite touching ten push sites and a custom
back affordance, and a deployment-target bump should be revertible on its own.

**Keep 15 and adopt `NavigationStack` behind `if #available(iOS 16)`.** Would restore swipe-back on
modern devices without a floor change. Rejected because it means maintaining two navigation models in
one app — the hand-rolled stack has to stay for the fallback — which is more code and more divergence
than the thing it avoids, in service of devices nobody owns.

## Consequences

- **Positive.** `NavigationStack` becomes available, which is the prerequisite for the phone getting
  system navigation — swipe-back, system titles, large-title collapse — instead of a hand-drawn bar.
- **Positive.** Every iOS availability branch currently in the tree becomes dead code and is removed
  in the same change, including the `Artwork` guard that predates all of this.
- **Positive.** The phone's chat composer can grow to multiple lines, which is what
  ADR-0022's Implementation block recorded as the cost of the floor.
- **Tradeoff.** Devices that cannot run iOS 17 — anything older than an iPhone XS — can no longer
  install the app. Nobody is affected today, and this is the decision that would have to be revisited
  if the app were ever distributed more widely.
- **Tradeoff.** The precedent cuts both ways: a floor that moves when an API earns it is a floor that
  will be asked to move again. Point 3 is the guard, and it is only as good as the next ADR.
- **Follow-up:** Adopt `NavigationStack(path:)` on the phone, retiring `backBar` and the manual
  `path.popLast()`. This is the payoff and it is deliberately not in this change.
- **Follow-up:** Reconsider `LibrarySidebar`'s and `LibraryView`'s header comments once
  `NavigationStack` lands — both explain a shape chosen because of the floor, and both will be
  describing history rather than a constraint.
