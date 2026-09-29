# ADR-0136: Familiar Server Runs in the Background

Status: proposed

Date: 2026-09-29

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

   It has no read-write file access.

3. **The Python server runs as its child and inherits its sandbox** (`Process`, with the child
   executables carrying `com.apple.security.inherit`). Familiar Server supervises it: restart on
   crash with backoff, and SIGTERM with a timeout on quit or logout, before Postgres is stopped.

4. **Postgres runs inside the same sandbox if the spike allows, and beside it if not.** The
   preferred form is Familiar Server's child, configured for the sandbox:
   - `listen_addresses='localhost'`
   - `unix_socket_directories=''`, because container paths exceed the socket-path limit
   - `shared_memory_type=mmap` and `dynamic_shared_memory_type=mmap`, because the sandbox
     restricts POSIX shared-memory names

   The fallback, if point 8 shows that fails, is an `SMAppService.agent` with hardened runtime and
   no sandbox, listening on loopback with a SCRAM password in Familiar Server's keychain. It never
   touches the music, so read-only enforcement is not weakened. Either way its data lives in
   Familiar Server's container.

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

7. **Its source is the Xcode project at `familiar/desktop/macos/`** (ADR-0135 point 2). It is a
   thin supervisor: all server behaviour stays in `backend/`, which the Docker form runs unchanged.
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
