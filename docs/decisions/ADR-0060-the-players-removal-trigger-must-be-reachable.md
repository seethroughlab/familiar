# ADR-0060: The Player's Removal Trigger Must Be Reachable

Status: accepted

Date: 2026-08-17

Extends [ADR-0058](ADR-0058-the-web-app-is-an-administration-tool.md) and **replaces its point 4**.

## Context

`ADR-0058` point 4 set the condition for deleting the web player:

> **when `docs/WEB-PARITY.md` shows no ❌ in the Mac and iPhone columns of its Listening table, the
> player is removed.**

It was written to fix a specific failure. `ADR-0050` point 3 had kept `/playlists/:id` "until the
Apple clients can edit a playlist"; that became true and nothing happened, because a condition in a
paragraph has nobody watching it. Point 4's answer was a condition you could check by reading one
file.

**It is checkable, and it can never be true.** Read against the Listening table today, five rows
carry a ❌ in a Mac or iPhone column:

| row | Mac | iPhone | can it ever clear? |
|---|---|---|---|
| Music Map | ✅ | ❌ | yes |
| New Releases detail | ❌ | ❌ | yes — needs a third embed-bridge message (`ADR-0020` point 3) |
| Network output (Sonos/UPnP/Chromecast) | ✅ | ❌ | yes — `ADR-0056` is proposed |
| **Listen-together (guest sessions)** | ❌ | ❌ | **no** |
| **Sleep timer, playback speed** | ❌ | ❌ | **no** |

- **Listen-together is web-only by an accepted decision.** `ADR-0036` built the server half and
  `ADR-0037` — hosting and joining on the Apple clients — was **rejected**. Its ❌s are not a gap
  anyone intends to close; they record a decision. Verified: `ADR-0037` reads `Status: rejected`.
- **Sleep timer and playback speed exist nowhere**, including the web column. A row that is ❌ on
  all three clients is not a reason to keep the web player, because the web player does not have it
  either. Verified: no `sleepTimer` / `playbackSpeed` / `playbackRate` implementation in
  `packages/frontend/src` or in `familiar-apple`; the single grep hit is inside the vendored
  `VisualizerBundle.html`.

So the trigger cannot fire, which makes it worse than the prose condition it replaced. A vague
condition at least gets argued about. **This one looks rigorous, sits in an accepted ADR, and
silently guarantees the player is never removed** — the exact outcome point 4 existed to prevent,
reached by the opposite route.

This is recorded plainly because the mistake is instructive: a mechanical trigger is only as good as
the data it reads, and nobody checked the trigger against the table at the time it was written.

## Decision

1. **The trigger is the Listening table's ❌ marks in the Mac and iPhone columns, excluding rows
   that cannot represent a gap.** Two exclusion rules, and they are the whole list:
   - **Excluded by decision** — the capability is web-only because an ADR decided it. Today:
     listen-together (`ADR-0037`, rejected).
   - **Excluded as absent everywhere** — the row is ❌ in the **Web** column too, so it is not
     something the browser provides and cannot be a reason to keep it. Today: sleep timer and
     playback speed.

2. **The excluded rows are marked in the table, not just here.** Each carries
   `**not a blocker:**` at the start of its Notes cell with the reason. The check stays "read one
   file": count ❌ in the Mac and iPhone columns, ignore rows whose Notes begin with that marker.

3. **A new exclusion requires an ADR.** Without this, the exclusion list is the obvious place to
   quietly move an inconvenient row, and the trigger would then fire early rather than never — the
   same defect pointing the other way. Adding a row to the list is a decision about what the browser
   is for, so it gets recorded like one.

4. **Three rows are the countdown, and they are named**: Music Map on iPhone, New Releases detail on
   Mac and iPhone, and network output on iPhone. When those clear, the player goes.

5. **The trigger is re-derived when the table changes, not assumed.** `ADR-0057` point 7 already
   makes `WEB-PARITY.md` the trigger and records that it went nine rows stale once. A row added to
   the Listening table is a row added to the countdown unless it is excluded under point 1.

## Alternatives Considered

- **Amend `ADR-0058` point 4 in place.** Much the simplest, and nobody would be misled by the
  result. Rejected because the convention forbids it: an accepted ADR's Decision is not edited to
  reflect a change of mind, precisely so that the reasoning behind a superseded condition survives.
  Here that reasoning is worth keeping — it explains why the trigger is mechanical at all.

- **Drop the mechanical trigger and go back to judgement** — remove the player when Jeff says so.
  Honest, and it is his call either way. Rejected because it is what `ADR-0050` point 3 did, and
  that condition came true unnoticed and stayed that way for months. The point of a file-checkable
  trigger is that it does not depend on anyone remembering.

- **Delete the two blocking rows from the table.** Tempting, and it would make the original trigger
  work unchanged. Rejected because the table's job is to be a complete record of what each client
  can do — `ADR-0050` point 6 makes it *the* reference — and deleting true rows to make a condition
  pass corrupts the thing every other decision reads.

- **Count only rows where the web has the capability and native does not** (i.e. Web ✅, Mac or
  iPhone ❌). This is nearly the same rule and needs no exclusion list, since it drops sleep timer
  automatically. Rejected because it does *not* drop listen-together — web ✅, native ❌ by
  decision — so an exclusion list is still needed for the case that actually matters, and a rule
  plus a list is clearer than a subtler rule plus a list.

## Consequences

- **Positive:** the player's removal has a condition that can actually be reached, and three named
  rows that say how far away it is.
- **Positive:** the countdown is short and concrete, which makes "how far from the goal are we" a
  question with an answer rather than an impression.
- **Tradeoff:** an exclusion list is a place where inconvenient rows can hide. Point 3 is the guard,
  and it is a procedural guard rather than a mechanical one — the weakest part of this ADR, named
  rather than papered over.
- **Follow-up:** `ADR-0056` (phone casting) is still `proposed`. Accepting and shipping it clears
  one of the three remaining rows.
- **Follow-up:** the Music Map and New Releases rows are both `familiar-apple` work, so the
  countdown is now mostly a native-client backlog rather than a web one.
