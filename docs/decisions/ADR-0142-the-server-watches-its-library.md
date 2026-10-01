# ADR-0142: The Server Watches Its Library

Status: proposed

Date: 2026-10-01

Extends [ADR-0136](ADR-0136-familiar-server-runs-in-the-background.md) point 10 and
[ADR-0117](ADR-0117-a-soulseek-download-is-a-pending-review-track-not-a-file-move.md)

## Context

Music copied into a library shows up at different times depending on the form of the server, and
the person adding it notices every time. **Familiar Server** watches its folder with FSEvents
(`FolderWatch`, ADR-0136 point 10) and starts a sync once the folder has been quiet for three
minutes (`SyncDebouncer`, `quietPeriod: 180`). **A Docker server** finds new music at its next
periodic sync, every two hours, unless someone starts one by hand. An album added at 10:01 can be
missing from the library until noon, which reads as the app being broken.

ADR-0117 point 3 rejected a filesystem watcher for the Soulseek inbox, saying "inotify does not
propagate reliably across bind mounts". **That premise does not hold for the way Familiar is
deployed.** Measured on the NAS on 2026-10-01: a container running the `v0.2.0-beta9` image, with a
scratch folder on the music disk bind-mounted into it, watched the folder with `watchfiles` (already
installed, through `uvicorn[standard]`); the host then wrote a file into it, then made a folder and
wrote a file in that. The container reported `added /w/sub/new.flac`, then `added /w/album2` and
`added /w/album2/t.mp3`, including the new folder's contents. Music copied to the NAS over SMB is
written by the host's own `smbd` to that same local disk, so it is the case measured. ADR-0117's
other reason, that a file appearing is the wrong signal for a *download finishing*, still holds, and
is about the inbox only.

Two numbers shape the design:

- **The library has 8,806 folders** (`find -type d`), against `fs.inotify.max_user_watches` of
  125,365 on the NAS. One watch per folder fits with room to spare.
- **A full sync costs about six minutes when nothing has changed** (the 20:00 and 22:00 periodic
  syncs of 2026-10-01: 26,615 unchanged; discovery, then the features and embeddings phases). Starting
  one for every album copied would put an hour of work on the NAS for ten albums.

## Decision

1. **The server watches its own library,** in the server process, with `watchfiles`. The same code
   runs in Docker, in a native Linux install and in Familiar Server: `watchfiles` uses inotify on
   Linux and FSEvents on macOS. Familiar Server's `FolderWatch` and `SyncDebouncer` are removed, so
   there is one implementation.

2. **A change is acted on once its folder has been quiet for three minutes,** the period Familiar
   Server already uses: an album being copied produces events for minutes, and acting on the first
   one imports one track of eleven, the failure ADR-0117 point 3 measured for downloads.

3. **What is acted on is a scan of the changed folders, not a sync.** It adds and updates files under
   those folders, applies the first-import rule (a new library's first import arrives active, not pending review) and queues new active tracks
   for analysis as approval does. **It never marks anything missing:** a scan that has not looked at
   the whole library cannot know what is gone, so deletions and moves stay with the periodic sync.

4. **The periodic sync stays,** unchanged, as the safety net for everything a watcher cannot see:
   network mounts on the machine running the server (SMB or NFS mounted into Familiar Server on a
   Mac, or into a container), changes made while the server was stopped, and deletions.

5. **The Soulseek inbox stays with its poll.** `background/soulseek.py`'s settled-folder check knows
   when slskd has finished a transfer, which a watcher cannot. The watcher ignores `Inbox/`.

6. **If the library cannot be watched, the server says so and carries on.** A folder that exceeds the
   watch limit, or a mount that does not support watching, logs one warning naming the cause, and the
   periodic sync covers it. The web admin's Overview shows whether new music is noticed at once or at
   the next sync.

## Alternatives Considered

- **Start the ordinary sync when the library goes quiet**, as Familiar Server does today. One code
  path. Rejected for the library at large: a sync with nothing new costs about six minutes on a
  28,000-file library, and the work grows with the library, not with what changed.
- **Make the periodic sync more frequent,** every ten minutes say. No watcher at all. Rejected: six
  minutes of work every ten, all day, mostly finding nothing, on the machine that also serves music;
  and still up to ten minutes late.
- **Watch from outside the container** (a host service calling the API). Survives any bind-mount
  doubt. Rejected: the measurement removed the doubt, and a host service is one more thing for each
  NAS owner to install, which Docker exists to avoid.
- **Keep watching in Familiar Server's app and add a watcher only for Linux.** Least change to the
  Mac. Rejected: two implementations of one behaviour drift; this ADR exists because they already
  had.

## Consequences

- **Positive:** an album copied to a NAS appears about three minutes after the copy ends, as on
  Familiar Server, without a full sync's cost.
- **Positive:** one implementation for both forms of the server.
- **Tradeoff:** deletions and moves still wait for the periodic sync. A track removed from the folder
  stays listed until then, and fails to play if chosen.
- **Tradeoff:** a library on a network mount gains nothing; the Overview says so rather than leaving
  the owner to wonder.
- **Follow-up:** every periodic sync on the NAS ends its features and embeddings phases with
  "forced exit: queue_churn_limit_exceeded:61/60:300s", which is most of its six minutes. Some tracks
  are requeued without end; that is its own defect, and fixing it makes the safety net cheaper.
