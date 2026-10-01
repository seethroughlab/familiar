# ADR-0140: Familiar Server Enforces Zero-Touch with a Seatbelt Profile, Not the App Sandbox

Status: accepted

Date: 2026-10-01

Implementation:
- **Accepted 2026-10-01**, as written.
- **Built 2026-10-01, points 1–5.**
  - `ServerLaunch` runs `/usr/bin/sandbox-exec -p <profile> -D MUSIC=<folder>` before Python. The
    folder is given with its symlinks resolved, because Seatbelt matches real paths.
  - The app and agent entitlements are empty, and the child keeps only numba's executable-memory
    exception. `FAMILIAR_SEMAPHORE_PREFIX` and `Identity.semaphorePrefix` are gone.
  - Sparkle's `SUEnableInstallerLauncherService` and its two `mach-lookup` exceptions are removed.
  - The folder is a plain bookmark, re-saved when stale, and read once when chosen so that the
    privacy prompt appears beside the picker.
  - `bringUp` refuses to start without `sandbox-exec`.
  - The app's data moves out of the sandbox container to `~/Library/Application Support/Familiar
    Server`. A build from before this starts over there; the only one ever installed was the first
    test install.
  - `scripts/integration-check.sh` now lets the app register its own agent, and checks launchd
    holds it. It runs on a library its owner can write, so a healthy server proves the profile is
    on, and its cleanup unregisters the agent through a debug-only switch.
  - **Not yet run** at the time of writing: the integration check, which needs port 4400 and the
    Postgres folder that a live test against a real library was using.

Supersedes points 2–4 of [ADR-0136](ADR-0136-familiar-server-runs-in-the-background.md), and
extends [ADR-0135](ADR-0135-familiar-server-is-a-separate-app.md)

## Context

ADR-0136 made Familiar Server a sandboxed app so that macOS, not only Familiar's code, would keep
the music folder unwritten (point 5). Postgres could not run in the sandbox: it always creates a
56-byte System V shared-memory segment as a postmaster interlock, and the App Sandbox refuses
System V shared memory. So point 4 put Postgres beside the sandbox, as an unsandboxed
`SMAppService.agent` that the sandboxed app registers.

**macOS forbids that combination.** The first install of a released build, `v0.2.0-beta8` on
2026-10-01, stopped with "Could not start the database: Operation not permitted". `smd` logged
why:

    smd: [com.apple.backgroundtaskmanagement:main] -[BTMManager registerLaunchItemWithAuditToken:…]:
         error: SMAppService target executable must be sandboxed because the app is sandboxed
    smd: [com.apple.xpc.smd:SMAppService] Register of <private> rejected by BTM.

Nothing had tested the registration. ADR-0136's spike record lists "`SMAppService` registration of
the login item and the agent" under **"Not covered by the spike, and still to prove"**, and
`scripts/integration-check.sh` starts the agent by hand, because approving a Login Item needs a
person. Points 2–4 rest on a premise that does not hold: a sandboxed app cannot register an
unsandboxed helper. A sandboxed helper cannot run Postgres. So the App Sandbox and Postgres cannot
both stay as decided.

What the App Sandbox was for is narrower than the sandbox: one rule, that the process tree reading
music cannot write it. macOS can enforce that rule without the App Sandbox. A Seatbelt profile
applied with `/usr/bin/sandbox-exec` restricts a process and every process it starts. Measured on
2026-10-01 with the bundled Python 3.11 and ffmpeg, under the profile

    (version 1)
    (allow default)
    (deny file-write* (subpath (param "MUSIC")))

- `os.access(music, W_OK)` returns **False**, so the zero-touch preflight is satisfied by the
  profile alone. `R_OK` is True.
- Creating, appending to, renaming and making directories in the folder: each `EPERM`. Reading
  works.
- A worker in a `spawn` pool, a child shell and ffmpeg: each refused a write to the folder, and
  ffmpeg could still write its cache elsewhere.
- A `multiprocessing` lock works with no semaphore prefix. The App Sandbox's restriction on POSIX
  semaphore names (ADR-0136 point 3) does not arise.

Those measurements used a local folder. Writing to the SMB share that motivated the first real
install was not attempted, because the only test there is a write into a person's library.

## Decision

1. **Familiar Server and its Postgres agent are not App-Sandboxed.** Both are signed with the
   Developer ID and the hardened runtime and notarized (ADR-0135). The app registers the agent with
   `SMAppService.agent`, which macOS allows for an unsandboxed app. The `app-sandbox`,
   `files.user-selected.read-only`, `files.bookmarks.app-scope` and `application-groups`
   entitlements go; `com.apple.security.inherit` goes from the child executables. Postgres's data
   and password stay where they are, in `~/Library/Group Containers/7JL9RZ9C8P.fs`, a path that no
   longer needs the group entitlement to reach.

2. **The Python server runs under a Seatbelt profile that denies writes to the music folder.**
   Familiar Server launches `python -m app.serve` through `/usr/bin/sandbox-exec`, with the profile
   above and the chosen folder as its `MUSIC` parameter. The profile is generated per launch,
   because the folder is the owner's choice, and it applies to everything the server starts:
   analysis pools, ffmpeg, fingerprinting, transcodes. It denies nothing else; the
   server's own data, caches and the network are untouched by it.

3. **Zero-touch is still enforced twice** (ADR-0136 point 5, kept): by the profile, and by
   `validate_library_path`, which refuses to start where `os.access(…, W_OK)` is True. The profile
   is what makes `os.access` False on a folder the owner could write. Without it, the server
   refuses to start, so a launch that skipped the profile fails closed instead of running
   unprotected.

4. **If `/usr/bin/sandbox-exec` is ever missing, Familiar Server refuses to start the server and
   says why.** It does not fall back to running unprotected. Its man page marks `sandbox-exec`
   deprecated, and macOS 26.6.2 still ships it, at `/usr/bin/sandbox-exec`.

5. **The folder is remembered as a path and a plain bookmark**, the bookmark to follow a moved or
   renamed folder. A security-scoped bookmark exists only for the App Sandbox. Reading a network
   volume, or Desktop, Documents and Downloads, is now governed by macOS's privacy prompts for the
   app, which the owner answers once.

## Alternatives Considered

- **Keep the App Sandbox and patch Postgres.** Familiar Server builds Postgres from source, so the
  System V interlock could be replaced and the agent sandboxed too. Rejected: that interlock is
  Postgres's guard against a second postmaster or an orphaned backend attaching to the same data
  directory. Replacing it means owning a change to the database's crash-safety code through every
  Postgres upgrade, for a property, read-only music, that a profile delivers without touching
  Postgres.
- **Drop OS enforcement and keep only the preflight.** The simplest build. Rejected: it gives up
  the reason ADR-0136 sandboxed anything. The preflight alone is a check the code performs on
  itself, which is the arrangement `docs/ZERO-TOUCH.md` and ADR-0136 point 5 set out to avoid.
- **A sandboxed app with an unsandboxed helper app embedded in it, which registers the agent.**
  Rejected: BTM judges registrations by the app bundle, so the nested helper would need to be its
  own unsandboxed bundle beside a sandboxed one. That is two processes and a channel between them,
  to keep an entitlement whose only remaining job a profile does.
- **Run Postgres in the sandboxed app's process tree.** Rejected for the reason ADR-0136 point 4
  already measured: the App Sandbox refuses System V shared memory.

## Consequences

- **Positive:** Familiar Server can register its database agent, which it never could. The
  integration check should exercise the real registration instead of starting the agent by hand.
  That depends on an unsandboxed app's agent being enabled on registration, with macOS's own
  notice and no approval step, which the build of this ADR has to confirm rather than assume.
- **Positive:** the protection is more precise. The App Sandbox granted read-only access to one
  folder and denied everything else. The profile denies exactly one thing: writing to the music.
- **Positive:** ADR-0136 point 3's semaphore adaptation is unnecessary on the Mac.
  `FAMILIAR_SEMAPHORE_PREFIX` is no longer set there, and the backend code that honours it stays
  for any future sandboxed form.
- **Tradeoff:** `sandbox-exec` is deprecated. If Apple removes it, point 4 makes the failure loud,
  and the decision would have to be revisited then. The preflight would still hold the line on a
  read-only mount.
- **Tradeoff:** the app process itself is unsandboxed. It reads the folder only to present it and
  to watch it (ADR-0136 point 10), and it writes only its own settings and the server's data.
- **Follow-up:** Sparkle (ADR-0135 point 3) no longer needs its installer launcher service or the
  two `mach-lookup` exceptions that the sandbox required. If that work merges first, they come out
  with this ADR's build.
- **Follow-up:** the first read of a network volume waits on a privacy prompt. On 2026-10-01 the
  server's startup check blocked in `opendir()` until the owner found and answered it. The app
  should read the folder itself when it is chosen, so that the prompt appears then, beside the
  picker, rather than behind the server's start.
- **Follow-up:** prove the profile on an SMB share, against a scratch folder outside the library.
