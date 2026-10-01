# ADR-0136: Familiar Server Runs in the Background

Status: accepted; points 2–4 superseded by [ADR-0140](ADR-0140-familiar-server-enforces-zero-touch-with-a-seatbelt-profile.md)

Date: 2026-09-29

Implementation:
- **2026-09-29, spike (point 8).**
  - **Method.** A throwaway sandboxed, headless app. It embeds PostgreSQL 16.15 and pgvector
    0.8.6, built from source with no dependencies outside the system, and python-build-standalone
    CPython 3.11.16 with the backend's locked numpy 1.26.4 and onnxruntime 1.24.1.
  - **Signing.** Every Mach-O is signed with the team's Apple Development identity (team
    `7JL9RZ9C8P`) with the hardened runtime and no exceptions. Executables carry `app-sandbox`
    and `inherit`.
  - **Launch.** Through LaunchServices on this Mac, writing a report into its container.
  - **Scope.** The music folder was granted with a read-only file entitlement standing in for
    the user-selected bookmark, which needs a click to grant.
  - **Harness.** Kept at `desktop/macos/spike/` to re-run once a Developer ID certificate exists.
  - Results:
    1. **Postgres cannot run in the sandbox.** `initdb` fails at the bootstrap backend:
       `could not create shared memory segment: Operation not permitted`,
       `shmget(key=…, size=56, 03600)`. That is the System V interlock, which no setting avoids.
       **Point 4 is revised to the agent.**
    2. **The agent works.** Postgres unsandboxed, hardened and signed by the same identity
       initialised and started. The sandboxed app's `psql` then ran over loopback:
       `CREATE EXTENSION vector`, 2,000 rows, an HNSW index, and a 10-nearest query using it.
    3. **`spawn` pools fail in the sandbox as they are** (`PermissionError` from `SemLock`).
       **They work with the app group and `semprefix`** (point 3): a `spawn` `Pool` and the
       backend's own shape, `ProcessPoolExecutor(spawn, max_tasks_per_child=1)` running numpy,
       both returned results.
    4. **Zero-touch holds, and the preflight can ask.** Listing and reading the music folder
       worked. Creating a file and appending to one failed with `EPERM`. `os.access(W_OK)`
       returned `False` for both the folder and a file.
    5. **No hardened-runtime exceptions.** CPython's extension modules and onnxruntime 1.24.1
       loaded under library validation, with everything signed by one team.
    6. **Size.** Before compression, and before ffmpeg, which was not measured:
       - the CPython 3.11 interpreter: about 66 MB
       - the backend's full `analysis` environment on 3.11: 665 MB, the largest part being
         llvmlite at 113 MB
       - PostgreSQL and pgvector: 30 MB

       The CLAP encoders (618 MB) are downloaded on first run and not bundled (ADR-0132 point 8).
       On 3.11 basic-pitch resolves to coremltools; on 3.12 it would need `tensorflow-macos`,
       which does not install.
  - **Correction to result 5, 2026-09-29.** "No hardened-runtime exceptions" held only for
    what the spike loaded: numpy and onnxruntime. The real backend imports librosa, whose numba
    JIT (llvmlite) makes memory executable. The first integration run was killed with `SIGKILL
    (Code Signature Invalid)` in `LLVMPY_TryAllocateExecutableMemory`. `cs.allow-jit` is not
    enough, because llvmlite maps without `MAP_JIT`, which was measured still crashing. The
    Python tree carries **`com.apple.security.cs.allow-unsigned-executable-memory`**. It applies
    to the process that reads music, and it widens what code may run, not what files may be
    written: the sandbox's read-only grant is unchanged.
  - **Not covered by the spike, and still to prove:**
    - `SMAppService` registration of the login item and the agent
    - a real `NSOpenPanel` grant and bookmark
    - signing with Developer ID and notarization. **The team has no Developer ID Application
      certificate**, only Apple Development and Apple Distribution (ADR-0135 needs one).

Extends [ADR-0131](ADR-0131-the-server-is-its-own-app.md),
[ADR-0132](ADR-0132-the-server-runs-without-docker.md),
[ADR-0135](ADR-0135-familiar-server-is-a-separate-app.md)

## Context

After ADR-0132 and ADR-0133, a Familiar server is:

- a Python process started with `python -m app.serve`
- a PostgreSQL 16 with pgvector
- `ffmpeg` on its `PATH`
- one data directory

ADR-0135 makes Familiar Server a separate Developer ID app, so what is sandboxed is chosen per
component. This ADR decides how that app runs the server on someone's Mac: through the day, whether
or not any player is open.

A fact about the server that shapes this decision: **the zero-touch guarantee
(`docs/ZERO-TOUCH.md`) is enforced only by Docker's read-only mount.** That document specifies a
startup check that fails if the library is writable. What exists instead is a warning:
`validate_library_path` (`app/main.py`) creates a temporary file in the library, and if that
succeeds it logs "Library path is writable" and starts anyway. On a writable library the check
therefore writes, and deletes, a file in the collection it exists to protect.
*(Correction, 2026-09-29: the first draft of this ADR said no check existed, because a search for
`W_OK` and `os.access` found nothing; the check uses `tempfile` instead.)* A person's own Music
folder is writable by that person, so a desktop server would lose the guarantee with only a log line
to show for it unless something else enforces it.

A second fact, which divides the problem: **of the server's processes, only Python reads music.**
Postgres stores what Python tells it. `ffmpeg` is spawned by Python against files Python names.
The read-only restriction has to hold for the Python process tree, and not necessarily for the
database.

## Decision

1. **Familiar Server is a menu-bar app (`LSUIElement`, no Dock icon) that starts at login.**
   - On first run it asks to start at login and registers itself with `SMAppService.mainApp`. macOS
     shows its own Login Items notice, and the owner can switch it off in System Settings.
   - Quitting Familiar Server from its menu stops the server until the next login or launch.
   - No player needs to be open, or installed on this Mac at all.

2. **Familiar Server owns the music folder.** It presents the folder picker on first run and keeps
   an app-scoped security bookmark. Its entitlements:
   - `app-sandbox`
   - `files.user-selected.read-only`
   - `files.bookmarks.app-scope`
   - `network.server`
   - `network.client`
   - `application-groups` = `7JL9RZ9C8P.fs`, deliberately short (point 3 says why)

   It has no read-write file access.

3. **The Python server runs as its child and inherits its sandbox** (`Process`, with the child
   executables carrying `com.apple.security.inherit`). Familiar Server supervises it: restart on
   crash with backoff, and SIGTERM with a timeout on quit or logout, before Postgres is stopped.

   **Its process pools need one adaptation.** The sandbox refuses POSIX semaphores unless their
   names begin with the app group and a slash, and every `multiprocessing` lock is a named
   semaphore (`sem_open`). So Familiar Server sets `FAMILIAR_SEMAPHORE_PREFIX=7JL9RZ9C8P.fs/mp`,
   and the backend copies it into `multiprocessing.current_process()._config["semprefix"]` beside
   its existing `set_start_method("spawn")` in `app/main.py`. This is a platform adaptation that
   ADR-0131 point 4 permits. The group id is short because macOS caps semaphore names at 31
   characters. `7JL9RZ9C8P.fs/mp-` plus Python's 8 random characters is 25.

4. **Postgres runs beside the sandbox, as an `SMAppService.agent`**, with the hardened runtime
   and no sandbox. It listens on `localhost` only, with `unix_socket_directories=''`, and uses a
   SCRAM password. *(Revised after the spike, point 8: the first draft preferred running it inside
   the sandbox. That cannot work. Postgres always creates a 56-byte System V shared-memory
   segment as a postmaster interlock, whatever `shared_memory_type` says, and the App Sandbox
   refuses System V shared memory outright.)*
   - It never touches the music, so the read-only enforcement in point 5 is not weakened: that
     holds for the process tree that reads files.
   - Its data directory and password file live in the app group container
     (`~/Library/Group Containers/7JL9RZ9C8P.fs`). The agent and the sandboxed server are both
     members, so each can reach them, and no Keychain item needs sharing.

5. **Zero-touch is enforced twice.** The sandbox denies writes to the music folder, because
   Familiar Server never held write access. And `validate_library_path` becomes the check
   `docs/ZERO-TOUCH.md` specified: it asks with `os.access` rather than by creating a file, and
   it refuses to start on a writable library rather than warning. It runs in Docker too, so an
   entitlement change or a compose file without `:ro` fails closed.

6. **The menu is the server's status surface:**
   - the current state (idle, syncing, analysing *n* of *m*, paused and why, per ADR-0138)
   - Open in Familiar (ADR-0134 point 5's pairing link to a player on this Mac)
   - Pair a Phone (the QR code)
   - Open Admin (the web admin, token in the fragment, ADR-0134 point 6)
   - Pause Analysis
   - Quit Familiar Server

7. **Its source is a Swift package at `familiar/desktop/macos/`** (ADR-0135 point 2), assembled
   into `Familiar Server.app` by a script, as the spike was, rather than an Xcode project. The
   package keeps the supervisor's logic in a library that `swift test` reaches without a GUI, and
   it avoids a hand-maintained `.xcodeproj` in a repository that has none. It is a thin
   supervisor: all server behaviour stays in `backend/`, which the Docker form runs unchanged.
   Nothing in `desktop/macos/` implements a feature the NAS would lack.

8. **Execution begins with a spike, and the rest of this ADR is shaped by it.** A throwaway build
   on a clean user account (not the author's desktop) must show:
   - whether Postgres 16 initialises, starts and runs `CREATE EXTENSION vector` under point 4's
     sandbox configuration
   - that the backend's `spawn` pools start inside the sandbox
   - that a write from the Python process into the chosen folder is denied
   - what `os.access(W_OK)` reports there, so the preflight tests the right thing
   - which hardened-runtime exceptions, if any, a bundled CPython with native extensions and
     onnxruntime needs to load
   - the total app size

   Each result is recorded in this ADR's Implementation block before the app is built out.

9. **The payload, built in CI and signed with the team's Developer ID:**
   - CPython 3.11 from python-build-standalone, matching the image's 3.11.15
   - a venv built by `uv` from `backend/uv.lock` with the `analysis` extra. On Darwin with Python
     3.11, basic-pitch resolves to coremltools, not TensorFlow. **From Python 3.12 it resolves to
     `tensorflow-macos`**, which has only cp311 wheels, so the extra does not even install
     (`uv.lock`; found 2026-09-29 when a 3.12 venv refused it). The 3.11 pin is load-bearing, not
     a matter of matching the image.
   - PostgreSQL 16 and pgvector as universal binaries
   - an LGPL build of `ffmpeg`/`ffprobe`
   - the backend, and the built web app in `static/`

   The CLAP artifacts are fetched on first run and verified (ADR-0132 point 8). yt-dlp is not
   bundled yet. ADR-0135 permits it, but a self-updating binary inside a sandboxed tree is its own
   question (Follow-up).

10. **Familiar Server notices new music.** It watches the bookmarked folder with FSEvents and
    requests a sync, debounced to a few minutes after the last change. The existing two-hourly sync
    (`CronTrigger(hour="*/2")` in `services/background/manager.py`) stays as the backstop. This is
    the supervisor's job, not the backend's: the NAS's library is on a bind mount, where the backend
    has no reliable way to watch (ADR-0117 chose polling for that reason).

## Alternatives Considered

- **A helper inside the player's bundle** (the previous draft). The player could start its own
  server, and there would be no second install. Rejected with ADR-0131's reversal: it made every
  player carry a server, and it needed the player out of the App Store.
- **A LaunchDaemon, system-wide and running as root.** It runs before login and serves every
  account. Rejected: it needs an administrator password to install, reads one person's music as
  root, and on a shared Mac cannot say whose library it is serving.
- **Unsandboxed, with the whole server under hardened runtime only.** Simplest to build, and
  Postgres certainly runs. Rejected for the Python tree, because it gives up the operating system's
  read-only enforcement for exactly the process that reads music, leaving zero-touch to a preflight
  alone. Kept for Postgres as point 4's fallback, where it costs nothing.
- **A plain launch agent with no app, configured from the web admin.** Nothing to build in Swift.
  Rejected: a background server with no visible presence is the thing people cannot find, pause or
  quit. Picking a folder securely needs a real open panel, and sandbox bookmarks need an app.

## Consequences

- **Positive:** the server runs from login whether or not a player is open, shows its state in the
  menu bar, and serves a player on this Mac, on another Mac or on a phone the same way.
- **Positive:** zero-touch is enforced by the operating system for the process that reads music, and
  the preflight finally exists everywhere.
- **Tradeoff:** a sandboxed app, a sandboxed Python tree and possibly a launch agent is more moving
  parts than the Docker stack it replaces for Mac users. The spike decides whether it is three parts
  or two.
- **Follow-up:** music videos on the desktop, when a self-updating `yt-dlp` inside a sandboxed tree
  has an answer.
- **Follow-up:** a CI job that builds the payload and runs the backend's smoke test against it, as
  `release.yml` does for the image.
