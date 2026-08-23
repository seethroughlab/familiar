# ADR-0074: The Queue Tag Names Three Different Things

Status: proposed

Date: 2026-08-18

Extends [ADR-0072](ADR-0072-paths-name-resources-tags-name-functions.md). Moves paths under
[ADR-0079](ADR-0079-a-moved-path-keeps-an-invisible-alias.md).

## Context

`queue` is six operations and three unrelated features. The prefix names a data structure that none
of them is:

| operation | what it actually is | decided by |
|---|---|---|
| `GET`/`PUT /queue/session` | playback-session persistence | `ADR-0003`, `ADR-0028` |
| `GET /queue/session/archive`, `POST …/{id}/restore` | archived session restore | `ADR-0028` |
| `POST /queue/suggestions` | radio — what to play next | `ADR-0005` |
| `POST /queue/offline-manifest` | the offline download manifest | `ADR-0006` |

Three ADRs, three features, one tag, and a prefix that suggests a fourth thing — a queue resource
you can read and modify, which does not exist. The Apple client's queue is local (`ADR-0028`); the
server persists a *session*, ranks *radio* candidates, and precomputes an *offline manifest*.

**Two of the six have no caller anywhere.** The generated Swift client calls
`queueGetPlaybackSession` and `queueSuggestions`. It does not call `queue_put_playback_session`,
`queue_list_archived_sessions`, `queue_restore_archived_session` or `queue_offline_manifest`, and
neither does anything in this repository once the web player is removed. That is a separate question
from this ADR's — it is `ADR-0077`'s — but it is worth knowing that four of the six operations being
retagged may not survive to need it.

**Why the paths move here when `ADR-0073` moved none.** `ADR-0072` point 4 moves a path only when it
misnames its resource, and `/queue/offline-manifest` is the clear case: there is no queue, the thing
being described is a download manifest, and a reader looking for offline behaviour has no reason to
open a file called `queue.py`. The same is true of radio.

## Decision

1. **`queue` becomes three tags at three prefixes:**

   | | tag | path |
   |---|---|---|
   | session persistence, 4 ops | `playback-session` | `/listening/session…` |
   | radio, 1 op | `radio` | `/radio/suggestions` |
   | offline manifest, 1 op | `offline` | `/offline/manifest` |

2. **`backend/app/api/routes/queue.py` is split to match**, into `listening/session.py`,
   `listening/radio.py` and `listening/offline.py`. It is ~700 lines for six endpoints today, which
   is the file-level form of the same conflation.

3. **Each moved path keeps an unschemad alias** under `ADR-0079`: `/queue/session`,
   `/queue/session/archive`, `/queue/session/archive/{id}/restore`, `/queue/suggestions` and
   `/queue/offline-manifest` continue to answer, invisibly, delegating to the same handlers.

4. **The alias removal trigger is recorded here.** These come out when no App Store build calling
   `/queue/*` is still offered. At the time of writing that is the `1.2` line; the exact build is
   named in the change that adds the aliases, per `ADR-0079` point 4.

5. **`/listening/` is a prefix, not a resource, and that is deliberate.** It groups the session
   under the activity it belongs to. It is the one place in this restructure where a path names an
   activity rather than a thing, and it earns it because "the session you are listening in" has no
   better noun — `/session` alone would collide with the listening-sessions feature being removed by
   `ADR-0070`, which is exactly the confusion to avoid inheriting.

## Alternatives Considered

**Retag without moving the paths**, as `ADR-0073` does throughout. This was the default and it is
the cheapest option — no aliases, no runtime risk, nothing reaching installed apps. Rejected for
`offline-manifest` and `suggestions` specifically: leaving them at `/queue/*` means the tag and the
path disagree permanently, and a newcomer resolving that disagreement has to read the git history,
which is the outcome this whole effort exists to prevent.

**Move the paths with no alias and coordinate the release.** Rejected by `ADR-0079`'s Context — the
repositories version independently and `familiar-apple` ships through App Store review.

**Keep one tag and rename it to something honest, like `listening-state`.** Genuinely considered: one
tag of six operations is easier to hold in the head than three of four, one and one. Rejected
because it is still three features, and the name would be a category invented to justify the
grouping rather than a description of it. `ADR-0072` point 7 tolerates a one-operation tag; it does
not tolerate a tag that means "assorted".

**Split the tags but leave `queue.py` whole.** Rejected as a half-measure that preserves the actual
obstacle: the file is where someone looks when they need to change radio ranking, and today they
find session persistence and manifest precomputation in the same 700 lines.

## Consequences

- **Positive** — three features become findable by their own names, in files named after them.
- **Positive** — the word "queue" leaves the server entirely, which matters because the queue is a
  client concept (`ADR-0028`) and the server's use of the word has been a persistent
  source of confusion about which side owns it.
- **Tradeoff** — five aliases, each needing a test that the old path still reaches the handler
  (`ADR-0079`'s Tradeoff), and each a thing to remember to remove.
- **Tradeoff** — `playback-session` is a hyphenated two-word tag where most are one word. The
  alternative, `session`, was rejected as too close to the feature `ADR-0070` deletes.
- **Follow-up** — four of these six operations have no caller. `ADR-0077` decides whether they
  survive; if they do not, this ADR's scope shrinks to `radio` and one session operation, and the
  aliases shrink with it. **Sequence `ADR-0077` first** to avoid building compatibility for something
  about to be deleted.
