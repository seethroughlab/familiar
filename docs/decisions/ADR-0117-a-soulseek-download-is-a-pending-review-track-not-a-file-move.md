# ADR-0117: A Soulseek Download Is a Pending-Review Track, Not a File Move

Status: proposed

Date: 2026-09-13

Extends [ADR-0116](ADR-0116-familiar-acquires-through-a-soulseek-client-it-does-not-own.md), whose
first follow-up asked for "a `soulseek_import_path` and a post-download move-and-sync". This ADR
records that the move half of that sentence was wrong, and what the loop actually needs.

Implementation:
- Built 2026-09-13 on `soulseek-tools`, alongside ADR-0116, ahead of acceptance.
- Point 2: `docker/docker-compose.inbox.yml` (opt-in) mounts `${SOULSEEK_INBOX_PATH}` at
  `/music/Inbox:ro`; the `/imports-incoming` mount is gone from the production file; `library_import/quick.py` (`GET /import/scan-path`)
  is deleted and `backend/openapi.json` regenerated. `.env.example` and `docs/INSTALLATION.md`
  document the variable.
- Point 3: `app/services/background/soulseek.py` — `SoulseekMixin._soulseek_poll`, registered in
  `BackgroundManager.startup` every `SOULSEEK_POLL_MINUTES` (2). `SoulseekService.downloads()`
  now carries `settled` per folder; `folders_to_trigger` is the pure rule;
  `familiar:soulseek:settled:<sha1>` in Redis holds the success count that last triggered, 30-day
  TTL. A running sync defers without marking (see `tests/test_soulseek_poll.py` for why).
- Point 6: `get_soulseek_transfers` reports `settled` and `sync_triggered` per folder; the
  download tool's note says Pending Review, not "a sync will be needed".
- Point 7: `_handoff()` in `handlers/soulseek.py`; `SoulseekService.download_root()` reads
  slskd's `/options`; `start_library_sync` is registered in `MUSIC_TOOLS` and always exposed.
  The first draft of this point reverted the reference installation's `rw` mount; the operator
  declined, and the point was rewritten — see Context.

## Context

**The premise that Familiar would move the files is contradicted by a principle already in
force.** Commit `5fe90d7a` (2026-03-19, "remove all library write paths for zero-touch mode")
deleted the organizer's execute paths, the import's file operations, the metadata writer
(935 lines), the FLAC remux, dedup deletion and the file-write scopes of proposed changes — 3,242
lines — and `docs/ZERO-TOUCH.md` states the promise those deletions serve: *Familiar never
creates, modifies, moves, re-encodes, or deletes files in the user's music library.* The
production compose mounts `/music:ro` with the comment "Familiar never writes to the library"
(`docker/docker-compose.prod.yml:96`, commit `d92e1fd8`). ADR-0116's follow-up was written
without having read this, and a `move-and-sync` would have been the first library write since
March. ADR-0116 is still `proposed`, so its follow-up bullet now points here; the reasoning
lives in this record so that it survives ADR-0116 being accepted.

**What zero-touch specified instead is already built, and is exactly the shape a download
needs.** `ZERO-TOUCH.md` §3 replaced import with an *inbox*: the listener puts files in a folder
that is part of the read-only library, the scanner discovers them like any other file, and they
enter `PENDING_REVIEW` rather than the library proper. That shipped. `scanner.py:470-477` marks
every truly new file `PENDING_REVIEW` and runs `detect_duplicate_for_track` on it, which records
`duplicate_of`, the match type and a `trump_status` comparing quality against what the library
has. `pending_review.py` serves it: groups by album (`/groups`), `approve`, `skip`, `unskip`,
`replace-upgrades` (the incoming track becomes active and the old one is `SKIPPED` — a DB change,
the old file stays where it is), `skip-downgrades`, group metadata edits, and bulk forms. Every
one of ADR-0116's named failure modes — partial folders, wrong tags, duplicates — already has a
DB-only answer in that queue.

**Two joints are missing, and neither is a write.**

1. *slskd's completed folder is not in the library's view.* The scanner walks one root, `/music`
   (`_discover_files_sync`, `scanner.py:174`). On the reference installation slskd completes
   downloads to `Downloads/complete`, which the compose already mounts — as `/imports-incoming:ro`,
   a path the scanner never visits. That mount was added by `bdc9f18c` for the copy-based import
   that `5fe90d7a` then removed; `GET /import/scan-path` still lists it and nothing in either
   client calls that endpoint. The plumbing for an inbox exists and points at nothing.

2. *Nothing tells the scanner a download has finished.* The periodic sync is a cron at every even
   hour (`background/manager.py:94-99`). A listener who said "yes, download it" at 20:05 has
   until 22:00 before Familiar notices, and the tool that queued it can only say "a sync will be
   needed". slskd knows the moment a folder completes; Familiar already polls slskd for
   `get_soulseek_transfers` and polls MusicBrainz every twenty minutes for discovery
   (ADR-0099), so a poll is an established shape here.

One fact about the reference installation, recorded so nobody re-derives it: its compose has
been locally edited to `/music:rw`. A draft of this ADR proposed reverting it. **The operator
declined**, and the reason matters: zero-touch is a promise about what *Familiar* does, not
about what the operator or their tools may do to their own disk. The mount's mode is theirs.
What this ADR governs is that no code path in Familiar writes through it — which holds
regardless of the mode — and that when a file *should* move, Familiar says so rather than doing
it. `ZERO-TOUCH-SIGNOFF.md`'s "make the mount read-only" item stays open as the operator's call.

## Decision

1. **Familiar does not move, rename, or delete a downloaded file, ever.** The zero-touch promise
   governs. What a download *becomes* is a `PENDING_REVIEW` track, found by the scanner at the
   path slskd wrote it to, decided on in the review queue, and left on disk whatever the decision.

2. **slskd's completed folder may be mounted inside the library, read-only — by opting in.** An
   override file, `docker/docker-compose.inbox.yml`, adds one mount:

   ```yaml
   - ${SOULSEEK_INBOX_PATH:?…}:/music/Inbox:ro
   ```

   An override rather than a defaulted line in the production file, because a default path would
   mount an *empty* `/music/Inbox` on every installation, and point 7's handoff would then report
   "inbox mounted, nothing to move" to operators who never asked for one. A bind mount nested
   inside another is ordinary Docker; the scanner sees `/music/Inbox/…` as
   part of the one root it already walks, and `_discover_files_sync` skips only symlinks. The
   `IMPORTS_INCOMING_PATH` / `/imports-incoming` mount is retired — it is this mount under its
   old, now-meaningless name — and `GET /import/scan-path` goes with it, since its only purpose
   was to list a folder the scanner now scans. An operator whose slskd already downloads into a
   subfolder of their library needs no inbox mount at all; the scanner finds those files today.
   The folder name is the operator's; `Inbox` is the default because it is what `ZERO-TOUCH.md`
   called it.

3. **A completed folder triggers a sync, on a poll, not on a file event.** When
   `soulseek_url` is configured, a background job asks slskd for its downloads every two
   minutes (`GET /api/v0/transfers/downloads`, one request, the same one
   `get_soulseek_transfers` makes). A folder is *settled* when every file in it is in a terminal
   state — `Completed, Succeeded` or a completed failure — and it has at least one success. A
   settled folder not seen settled before starts `run_sync()` if no sync is running; the
   folder is remembered in Redis so it triggers once. Not a filesystem watcher: inotify does not
   propagate reliably across bind mounts, and the scanner has no watcher to attach one to; and
   not per-file, because slskd moves each file from `incomplete` to `complete` as it finishes,
   and a sync fired on the first file imports one track of eleven and then fires ten more times.

4. **The sync is the ordinary one.** No path-scoped scan, no "import this folder" endpoint. The
   incremental sync already costs little for unchanged files (mtime and size before any hash),
   and a scan that only looked at the inbox would need a second entry point, a second progress
   surface and a second set of failure modes for something the existing one does by walking
   past the same files. If the inbox ever makes the full walk too slow, that is a scanner
   performance question and gets its own record.

5. **Duplicates and partial folders are the review queue's, and it already handles them.** A
   FLAC of an album the library holds as MP3 arrives as `PENDING_REVIEW` with
   `trump_status: "trumps"`, and `replace-upgrades` makes it the active copy — the MP3 files stay
   on disk, `SKIPPED` in Familiar. A folder that settled with three of eleven tracks failed is a
   group of eight in the queue; when slskd retries and the rest complete, the folder settles
   again with more successes than before and triggers again, and the eight already reviewed are
   unchanged files the sync skips. Nothing here is new behaviour; the point is that it needs
   none.

6. **The tools say what is true.** `download_from_soulseek`'s note today says the files "appear in
   the library once that folder is visible to a library sync"; with this ADR it says they will
   appear in Pending Review within a few minutes of the transfer finishing, where the listener
   accepts or skips them. `get_soulseek_transfers` reports, per folder, whether it has settled and whether
   its sync has been triggered, so a host can answer "is it in yet?" without guessing.

7. **When a move is needed, Familiar hands it off; it does not do it.** Not every installation
   mounts an inbox, and an operator may prefer downloads filed as `Artist/Album` rather than
   living under `Inbox/` forever. So `download_from_soulseek` and `get_soulseek_transfers`
   return a `handoff`: the folder name, its path *as slskd sees it* (from slskd's own
   `/options`, since Familiar cannot know the operator's host paths), whether an inbox is
   mounted, the library path, and one sentence saying what to do — nothing, if an inbox is
   there; otherwise "move the folder into the library, then call `start_library_sync`". The
   mover is whoever has hands: the listener, or an MCP host that has its own shell access to
   the machine. That access is the host's, granted by the operator, and is not routed through
   Familiar — the MCP surface carries instructions, never a move. `start_library_sync` is the
   one new general tool: it starts the ordinary sync so the host can finish the job without
   waiting for the cron, and touches nothing on disk.

## Alternatives Considered

- **Move the folder from the inbox into the library, organised by template.** ADR-0116's original
  wording. Rejected by `5fe90d7a` and `ZERO-TOUCH.md` §2, which deleted exactly this — the
  organizer's execute path — six months ago on purpose. The tradeoffs that ADR-0116 named as the
  reason to defer (partial folders, tags, duplicates) were the tradeoffs zero-touch resolved by
  making them review decisions rather than file operations. Reversing a core promise for the
  convenience of one integration is not a decision this ADR can make; it would need its own,
  superseding the principle, and this ADR's author does not think it should be made.
- **Let Familiar move the folder when the host asks, as a tool.** The host is going to do it
  anyway when it has a shell; why not one call? Rejected because the promise is about Familiar's
  code paths, and a tool that moves files *is* one — on every installation, exposed to every
  host, whatever the operator intended when they mounted `rw`. A host that moves a file over SSH
  is acting on the operator's grant to *it*; a tool that moves a file is Familiar acting on a
  grant nobody made. The handoff is the same outcome with the responsibility where it belongs.
- **Have slskd download straight into the library root, with no inbox.** Works today with no code
  change, and point 2 leaves it available. Not the default because it puts a stranger's folder
  names and half-finished transfers at the top level of the collection, where the operator
  browses; an `Inbox` is the same files with a fence around them.
- **A `POST /library/sync?path=/music/Inbox` scoped scan.** Rejected by point 4. Faster per call,
  but it is a second scan entry point whose only caller would be this poll, and the scanner's
  relocation-by-hash logic (`scanner.py:458`) assumes it has seen the whole library — a scoped
  scan that finds a hash it knows would misreport a relocation.
- **Trigger the sync from `get_soulseek_transfers`.** The tool already fetches the data. Rejected
  because it makes the outcome depend on the listener asking: a download that finishes after the
  conversation ends waits for the two-hour cron. The tool *reports* settled/triggered (point 6);
  the background job does the triggering.
- **A filesystem watcher on `/music/Inbox`.** Rejected — see point 3. Also the wrong signal: a
  file appearing is not a folder finishing.
- **Per-file sync triggers.** Rejected — see point 3's last sentence; measured cost is one sync per
  track.
- **Auto-approve Soulseek downloads, skipping review.** The listener already said yes once.
  Rejected because the yes was to *fetching* a folder from a stranger, not to what turned out to
  be in it: wrong-artist folders, 128 kbps rips labelled FLAC, and duplicates of what the library
  has are all things the review queue was built to catch, and it catches them with trump
  comparison the tool cannot do before the bytes arrive. A follow-up below offers the queue to
  the host so the second yes is one sentence.

## Consequences

- **Positive:** the loop closes with no new write path. Recommend → fetch → appears in Pending
  Review → accept. Every step after "fetch" is code that shipped in March.
- **Positive:** zero-touch is kept as a statement about Familiar's code — no path in it writes
  to the library, on any installation — and a dead mount and a dead endpoint are removed. The
  mount's mode is left to the operator.
- **Positive:** the same inbox serves every acquisition, not only Soulseek. A Bandcamp download
  dropped in the folder by hand takes the same path; the poll is the only Soulseek-specific part.
- **Tradeoff:** latency is the poll interval plus the sync — a few minutes, not seconds. Chosen
  over a watcher for the reasons in point 3.
- **Tradeoff:** a sync is the *whole* sync, including the analysis phases. On a large library the
  walk is minutes; on the reference installation the incremental pass is dominated by the new
  files' analysis, which is the work that had to happen anyway.
- **Tradeoff:** a settled folder with zero successes never triggers. That is correct — there is
  nothing to scan — but it means a wholly failed download is visible only in
  `get_soulseek_transfers`, not in Pending Review. The tool's report covers it.
- **Follow-up:** two MCP tools over the review queue — `list_pending_review` (groups, with
  trump status) and `approve_pending_group` / `skip_pending_group` — so the host that queued the
  download can offer "eleven tracks, 24-bit FLAC, upgrades your MP3 copy: accept?" and act on
  the answer. Deliberately not here: it widens the MCP surface into management, which is a
  decision about the surface, not about downloads.
- **Follow-up:** the zero-touch preflight (`ZERO-TOUCH-SIGNOFF.md`, "fail or warn loudly if the
  configured library path is writable") would have caught the reference installation's `rw`
  edit. Still open; still worth doing; not this ADR.
- **Follow-up:** `Inbox` groups in Pending Review could show where they came from (the slskd
  sharer, the query) by joining on the folder path the poll recorded. Cosmetic until someone
  asks "why is this here?".
