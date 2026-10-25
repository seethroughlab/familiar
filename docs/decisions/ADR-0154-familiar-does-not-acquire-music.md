# ADR-0154: Familiar Does Not Acquire Music

Status: proposed

Date: 2026-10-25

Supersedes [ADR-0116](ADR-0116-familiar-acquires-through-a-soulseek-client-it-does-not-own.md) and
[ADR-0117](ADR-0117-a-soulseek-download-is-a-pending-review-track-not-a-file-move.md).

## Context

ADR-0116 gave Familiar four Soulseek tools over an operator's slskd. ADR-0117 then got a download
into the library without a file move: it mounted slskd's completed folder read-only at
`/music/Inbox`, polled slskd every two minutes and started a sync once a folder settled. Both work,
and the NAS runs with the inbox mounted.

The direction has changed, not the engineering. Familiar's discovery tools already end at places to
buy music (`recommend_bandcamp_purchases`, `search_bandcamp`), and the intent is to **send listeners
to Bandcamp**. A server that is "meant to be run by other people" (ADR-0116's own Context) and also
offers to fetch the album it just recommended from a stranger over P2P contradicts that. Anyone at a
store reading the tool list would see the contradiction first. The listener still wants the
Soulseek tools, but as their own tools, not as a feature of Familiar.

**ADR-0116 rejected exactly this split, and its reason is contradicted here rather than ignored.** It
said "the value is in the join": "you don't have this" comes from the library and "here it is" from
slskd, and two servers cannot make one call of it. That is true. `find_missing_on_soulseek` was the
one call, and it goes. The check it made — library first — becomes an instruction in the separate
server, the way `jeff-tools` (the predecessor, once `slskd-mcp`) carried it in its `CLAUDE.md`: a
host with both servers searches the library, then Soulseek. That gives up a guarantee for a
convention. It is the cost of Familiar not acquiring music.

**ADR-0117's zero-touch reason for the Inbox does not survive the split, and does not need to.**
Zero-touch (`docs/ZERO-TOUCH.md`, ADR-0140) is a promise about Familiar: it never writes the music
folder. A separate tool the listener runs can move a finished download into that folder without
Familiar touching it. ADR-0142's watcher then scans the folder once it has been quiet for three
minutes. Review is not lost either. `docs/ZERO-TOUCH.md` already sends every newly discovered file
to `PENDING_REVIEW` except during a library's first import. All the Inbox added was the mount, plus
a rule that it is reviewed during a first import too (`scanner.py:276`, `:506`).

What is there now: 66 tracked files mention Soulseek or slskd. The core is `services/soulseek.py`
(516 lines), `llm/handlers/soulseek.py` (277), `background/soulseek.py` (139), `routes/soulseek.py`
and `operations/soulseek.py`, three test files (1,048 lines), `SoulseekSettings.tsx`, the
`soulseekApi` adapter, and `docker-compose.inbox.yml`. The tools are withheld unless configured
(`mcp/server.py:74`, `withheld_tools()`), so an installation without slskd has never seen them.

## Decision

1. **Familiar has no acquisition tools.** `search_soulseek`, `download_from_soulseek`,
   `get_soulseek_transfers` and `find_missing_on_soulseek` are deleted, along with their handlers,
   the slskd gateway, the `/soulseek/status` route and operation, the settings fields
   (`soulseek_url`, `soulseek_api_key`) and the Server → Providers card. The two discovery guidance
   strings that offer `find_missing_on_soulseek` (`mcp/guidance.py:43`, `:48`) go too. The Bandcamp
   links stay; they are how a recommendation ends now.

2. **The Inbox is deleted, not generalised.** `docker-compose.inbox.yml`, `SOULSEEK_INBOX_PATH`,
   the watcher's `Inbox/` exclusion (`library_watch.py:38`) and the scanner's first-import exception
   (`scanner.py:276`) go. A folder named `Inbox` becomes an ordinary library folder. New files reach
   Pending Review by the ordinary rule.

3. **The Soulseek poll is deleted.** `SoulseekMixin` and the `soulseek_poll` job
   (`background/manager.py:225`) go. Nothing in Familiar asks slskd anything.

4. **`start_library_sync` stays.** It is in `MUSIC_TOOLS`, not `SOULSEEK_TOOLS`, and it is how any
   outside tool says "look now" rather than waiting for the watcher.

5. **Acquisition lives in `soulseek-mcp`, a separate repository.** It took the slskd client and its
   tests from here unchanged in substance. The two measured slskd facts from ADR-0116 point 4 and
   point 5 stay pinned there. It adds a `move_download_to_library` tool, which renames a *settled*
   folder to `<library>/<Artist>/<Album>`, refuses an existing destination and works locally or over
   `ssh`. It never imports anything from Familiar and knows nothing about it beyond the instruction
   to check a library first.

6. **The structural examples get new subjects, not stubs.** Soulseek was the first slice of two
   structural ADRs: the one gateway in `app/container.py` (ADR-0130) and the eleven-file trace in
   `docs/START-HERE.md` (ADR-0127), which `scripts/check_docs.py` audits. The container keeps its
   shape with no gateway until the next domain moves in; `Services.unconfigured()` stays as the
   named null. START-HERE's trace is re-pointed at another feature already on the generated path,
   checked by `check_docs.py` like the first.

## Alternatives Considered

- **Keep the tools, withheld by default.** They are already withheld on every server without
  slskd, so this is the status quo. Rejected because the problem is what Familiar *is*: the tools
  ship in every image and are documented in `INSTALLATION.md`. Being hidden does not make them
  absent from the product.
- **Keep the Inbox as a generic, reviewed drop folder.** Its comments already name "a Bandcamp
  download folder, a phone sync target", and it would let a download appear without a move.
  Rejected by the listener. Once the poll is gone, an Inbox is just a library folder with a special
  case in two places. The ordinary watcher and Pending Review already cover a folder moved in. A
  mount is one more thing an installer has to understand.
- **Move the code into `jeff-tools` instead of a new repository.** `jeff-tools` is the predecessor
  and already holds a Soulseek client. Rejected for now. It is not under version control, it mixes
  Soulseek with Spotify and Familiar-API tools, and its Familiar client is out of date: it calls
  `/library/import/scan-path`, which ADR-0117 deleted, and sends no `X-Familiar-Token` (ADR-0141).
  Its clear-downloads tool called `DELETE /transfers/downloads`, which matches no route in slskd's
  `TransfersController`. A new repository with the tested client is a cleaner base.
- **Have `soulseek-mcp` call Familiar's API to check the library.** That would restore
  `find_missing_on_soulseek`'s join across the boundary. Rejected: it couples a general Soulseek
  tool to one player's API and token. The host already has Familiar's MCP server and can make the
  call itself.

## Consequences

- **Positive:** Familiar's description of itself is true without qualification: it plays, analyses
  and recommends, and when it recommends something you lack, it points at a store.
- **Positive:** about 2,300 lines and three background concerns leave the server. The two-minute
  poll no longer runs on every installation in order to find out it has nothing to do.
- **Tradeoff:** the library-first check is now a convention in a host's instructions rather than a
  property of one call. A host can search Soulseek for an album already on disk.
- **Tradeoff:** the NAS loses automatic arrival. Until `soulseek-mcp`'s move tool is configured
  there, a finished download sits in slskd's completed folder. The NAS must also drop the inbox
  override when this ships: the `-f docker-compose.inbox.yml` in its compose command and the
  `COMPOSE_FILE` line in its `.env`, both quoted in `START-HERE.md`. Otherwise compose fails on a
  missing file.
- **Tradeoff:** removing the settings fields is a contract change, so the schema is regenerated and
  `familiar-apple` must re-vendor it (`scripts/vendor-schema.sh --fetch`), as after any schema
  change.
- **Follow-up:** `CLAUDE.md`'s paragraphs on ADR-0116/0117, ADR-0129's "Soulseek status is the first
  feature on the generated path" and ADR-0130's Implementation block are rewritten to say what
  replaced them once this is accepted. Their Status lines change to `superseded by ADR-0154`.
