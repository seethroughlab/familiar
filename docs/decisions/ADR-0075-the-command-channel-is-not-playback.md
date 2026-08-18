# ADR-0075: The Command Channel Is Not Playback

Status: proposed

Date: 2026-08-18

Extends [ADR-0072](ADR-0072-paths-name-resources-tags-name-functions.md). Moves paths under
[ADR-0079](ADR-0079-a-moved-path-keeps-an-invisible-alias.md).

## Context

The API contains two unrelated things called playback, and neither of them is playback.

**`routes/playback.py`, tag `playback`, two operations.** `GET /playback/commands` is the
server-sent-event channel an MCP client uses to actuate a native player (`ADR-0044`), and
`POST /playback/artifacts/{request_id}` is where a client uploads what it was asked to capture
(`ADR-0053`). Nothing here plays anything: the server neither decodes audio nor holds a transport.
It is a command bus, and the one on the *receiving* end is the Apple client.

**`routes/tracks/playback.py`, tag `tracks`, five operations.** `started`, `played`, `skipped`,
`rejected` and `report-playback-error` — the listening-event record `ADR-0004` built the recommender
on. This is history, not control.

So the word appears twice, in two files, for a channel and a ledger, and the tag belongs to the one
that is neither. Someone changing how a skip is recorded has a fair chance of opening the wrong file;
someone looking for the MCP channel has no reason to open either.

**The cost here is unusual, and it is the reverse of `ADR-0073`'s.** `playback` is **not** in
`filter.tags`, so the tag rename is entirely free — no Swift symbol changes. But the *paths* are
consumed by hand-written Swift rather than by the generated client:
`App/Shared/PlaybackCommandClient.swift:144` builds `api/v1/playback/commands` and `:210` builds
`api/v1/playback/artifacts/{id}`. A path move therefore reaches installed applications with no
compile error anywhere to warn about it — the worst of the three cost classes, on a surface that
looked like the cheapest.

## Decision

1. **The tag becomes `commands`.** This is free and immediate: `playback` is outside the generated
   surface, so nothing regenerates and no Swift symbol moves.

2. **`routes/tracks/playback.py` becomes the `plays` tag**, under `ADR-0073` point 2, and the module
   is renamed to `listening/plays.py`. The word "playback" stops naming two things by naming
   neither.

3. **The paths move to `/commands/…`** — `/commands/stream` for the SSE channel and
   `/commands/artifacts/{request_id}` for the upload — **with unschemad aliases** under `ADR-0079`.
   `/playback/commands` and `/playback/artifacts/{request_id}` keep answering.

4. **The alias here outlives the others, and the reason is recorded.** `ADR-0079` point 4's trigger
   is "no offered build calls the old path", and the caller is hand-written rather than generated —
   so its removal cannot be verified by regenerating a client and seeing what fails to compile. The
   check is a grep of `App/Shared/PlaybackCommandClient.swift` in the oldest offered build, and it
   is written into the change that adds the alias.

5. **The path move is justified rather than assumed.** It is the one place in this set where a
   path moves at real risk, and it earns it: `ADR-0044` and `ADR-0053` describe a general command
   channel that is expected to grow, and every command added under a `/playback/` prefix would
   compound the misnomer. Renaming costs one alias now and nothing later; not renaming costs a
   little confusion forever.

## Alternatives Considered

**Rename the tag and leave the paths.** The cheapest correct-ish option, and the one that nearly
won: the tag is what a newcomer reads in `/docs`, and it would be free. Rejected on point 5's
reasoning — the prefix is the thing hand-written clients type, and it is the part that will be
copied when the second and third commands are added.

**Leave both alone; two things called playback is survivable.** Rejected because the collision is
not between a tag and a prefix but between two *modules*, one of which is nested inside the other's
resource. `routes/playback.py` and `routes/tracks/playback.py` is a naming collision that no
convention resolves, and the restructure is the moment it is cheapest to fix.

**Move only `tracks/playback.py` and leave `/playback/*` as the command channel.** This fixes the
module collision for free — the `plays` retag is already happening under `ADR-0073`. Rejected
because it leaves the *worse* of the two names in place: a ledger renamed to `plays` is correct, but
a command bus still called playback is the one that actively misleads, and it is the one an MCP
integrator meets first.

**Name it `mcp` rather than `commands`.** Rejected because `ADR-0044`'s channel is defined by what it
carries, not by who happens to send on it today; the MCP server is one producer, and the tag should
not have to be renamed again when there is a second.

## Consequences

- **Positive** — the tag change costs nothing and can land in the free phase, ahead of everything
  coordinated.
- **Positive** — `playback` stops being a word that means two things, and `routes/playback.py` stops
  shadowing `routes/tracks/playback.py`.
- **Positive** — the command channel gets a prefix it can grow into, which `ADR-0044` and `ADR-0053`
  both anticipate.
- **Tradeoff** — this is the highest-risk path move in the set, because the caller is hand-written.
  A generated client would fail to compile; this one fails at runtime, in the field, on a surface
  used by an agent rather than watched by a person.
- **Tradeoff** — point 4's removal check is a grep of another repository's shipped source, which is
  weaker than every other trigger in this set.
- **Follow-up** — the hand-written `PlaybackCommandClient` is the reason this is risky. Whether the
  command channel should be in the generated surface at all is a real question and not this ADR's:
  `ADR-0007` point 8 deliberately excludes SSE endpoints, so the answer today is no, and the artifact
  upload could be generated even if the stream cannot.
