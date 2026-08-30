# ADR-0075: The Command Channel Is Not Playback

Status: accepted

Date: 2026-08-18

Extends [ADR-0072](ADR-0072-paths-name-resources-tags-name-functions.md). Moves paths under
[ADR-0079](ADR-0079-a-moved-path-keeps-an-invisible-alias.md).

Implementation:

- **Shipped 2026-08-28**, both repositories on `adr-0075-command-channel`, stacked on `ADR-0074`'s.
  This closes the API cluster: `0077` → `0072` → `0073`/`0074`/`0076` → `0075`.
- Point 1 was free exactly as predicted: `playback` is not in `filter.tags`, and the generated Swift
  client came back **byte-identical**. Point 3's two paths moved with aliases, which exist because
  `ADR-0074` built `ADR-0079`'s module.
- **Point 2 was implemented as `tracks/plays.py`, not `listening/plays.py`.** The ADR's goal is to
  stop `routes/playback.py` shadowing `routes/tracks/playback.py`, and renaming the inner module
  achieves it. Moving it to `listening/` would have put routes whose paths are `/tracks/{id}/played`
  — which `ADR-0073` point 3 deliberately does not move — into a package aggregated under a
  different prefix, forcing `tracks/__init__.py` to import its own routes back out of `listening/`.
  The collision is resolved; the file simply sits where its paths do.
- `routes/playback.py` became `routes/commands.py` and `tests/test_playback_commands.py` became
  `tests/test_command_channel.py`, so the word stops appearing where the ADR says it misleads.
- **The Tradeoff is worse than the ADR states, and this is the thing to carry forward.** It says a
  generated client would fail to compile while this one fails at runtime. True — but there is also
  **no test anywhere in `familiar-apple` that asserts either path**. `PlaybackCommandClient` builds
  them with `appendingPathComponent` and nothing checks the result, so the only things standing
  between a typo and a silently dead command channel are a grep and the server-side alias.
- **That gap is not closed here, and the reason is structural.** `PlaybackCommandClient` lives in
  `App/Shared`, which is outside the Swift package and therefore unreachable from `swift test` — the
  same seam `ADR-0073` hit from the other direction. Testing the URL construction means moving the
  client into `FamiliarKit`, which is a larger change than this ADR's scope and is recorded as a
  follow-up rather than smuggled in.

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
- **Follow-up, now done (2026-08-28)** — the paths are asserted. Rather than move the whole
  `ObservableObject` — it depends on `ServerConfiguration`, `FamiliarPlayer` and UIKit, all app-target
  things — only the URL construction moved, to `FamiliarKit.PlaybackCommandEndpoints`, which is the
  seam `PlaybackCommandClient`'s docstring already described. Five tests cover it, and they were
  checked to *fail* on a reverted path rather than merely to pass.
- **Follow-up** — the hand-written `PlaybackCommandClient` is the reason this is risky. Whether the
  command channel should be in the generated surface at all is a real question and not this ADR's:
  `ADR-0007` point 8 deliberately excludes SSE endpoints, so the answer today is no, and the artifact
  upload could be generated even if the stream cannot.
