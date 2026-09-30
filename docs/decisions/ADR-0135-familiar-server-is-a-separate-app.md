# ADR-0135: Familiar Server Is a Separate App Distributed with Developer ID

Status: proposed

Date: 2026-09-29

Extends [ADR-0131](ADR-0131-the-server-is-its-own-app.md)

## Context

ADR-0131 makes the server its own product, with a macOS form called Familiar Server. This ADR
decides how that app is built, signed, shipped and updated, and what happens to the player.

The player ships through App Store Connect: `familiar-apple/scripts/release-mac-app-store.sh` is
`release-app-store.sh --platform macos`. Three facts rule out doing the same for a server:

- **App Review would gate every server release that reaches a desktop user.** A backend fix reaches
  the NAS the same day, through a tagged image. Inside a Mac App Store build it would wait for review,
  measured in days, and could be refused. That would put the two supported server forms (ADR-0131
  point 2) on different schedules for the same code.
- **The Mac App Store requires every executable to be sandboxed.** The server runs Postgres, a
  Python interpreter, spawned analysis pools and `ffmpeg`. Postgres under the App Sandbox is
  unproven (ADR-0136 point 8). Outside the store, whether to sandbox becomes a per-component choice
  instead of a condition of distribution.
- **Guideline 2.5.2 forbids downloading executable code.** `yt-dlp` updates itself at every
  container start (`docker/entrypoint.sh`), and a server that must never do the same is a narrower
  server than the Docker one.

None of that applies to the player, which stays a sandboxed client (`network.client` is its only
other entitlement, in `familiar-apple/Support/Familiar-macOS.entitlements`).

The previous draft of this ADR moved the player *out* of the store to carry the server. ADR-0131
records why that was reversed: it tied the listening machine to the server machine.

## Decision

1. **Familiar Server is a separate Mac app, distributed as a Developer ID-signed, notarized
   `.dmg`** from the GitHub release. It has its own bundle identifier (`com.familiar.server`) and
   is not submitted to the Mac App Store.

2. **Its source lives in `familiar`, at `desktop/macos/`**, beside the backend it packages. The
   release workflow builds it from the same tag as the Docker image, so the two server forms are the
   same version by construction, and nothing is vendored from one repository into another. Its CI
   job runs on the self-hosted macOS runner that `ci.yml` already uses (`[self-hosted, macOS]`).

3. **Updates come through Sparkle**, from an appcast the release workflow publishes beside the image.

4. **The player stays in the Mac App Store, and iOS is unchanged.** Neither gains any server code,
   entitlement or payload.

5. **The two apps meet only through pairing.** Familiar Server's first run offers links to get the
   player (App Store) and the phone app. Once a player is installed, "Open in Familiar" hands it the
   server through ADR-0134 point 5's pairing link. The apps share no app group, container or
   bundle. A Familiar Server on one Mac serves a player on another exactly as it serves one on the
   same Mac.

## Alternatives Considered

- **Move the player out of the Mac App Store and put the server inside it** (this ADR's previous
  draft). One download, and no pairing step on the same Mac. Rejected: every NAS user's player
  would carry a server it never starts, and the store's install, trust and updates would be given up
  for the one arrangement the author's own setup shows is not universal (ADR-0131 Context).
- **Ship Familiar Server through the Mac App Store as well.** One distribution channel and trust
  model for both apps. Rejected on cadence and on the sandbox, both in Context. A server whose fixes
  wait on review while the NAS image ships the same hour inverts ADR-0131 point 2's parity.
- **Keep Familiar Server's source in `familiar-apple`.** That repo already has Xcode CI, the
  signing identity and Swift conventions. Rejected: every backend release would have to be vendored
  across to build the server app, as the schema already is, and the two server forms could then
  drift in version. That is the kind of cross-repository lag CLAUDE.md already warns about for the
  schema ("every `familiar-apple` branch fails CI until `scripts/vendor-schema.sh --fetch` is run").
- **Two builds of the player, an App Store client and a Developer ID build with the server.**
  Nobody is forced to choose. Rejected: "which Familiar do you have?" becomes a support question,
  and every Mac feature is tested twice.

## Consequences

- **Positive:** a server fix reaches Mac servers and NAS servers from the same tag on the same day.
- **Positive:** the player keeps the Mac App Store's install, trust and automatic updates.
- **Tradeoff:** a coworker installs two things. Point 5 makes the second a click from the first,
  but the site's install panel has to explain it in one sentence ("the server holds your music;
  the app plays it").
- **Tradeoff:** `familiar` gains Swift, an Xcode project, notarization and a Sparkle signing key. A
  leaked Sparkle key is a route to every desktop server, so it is kept as a repository secret used
  only by the release job.
- **Follow-up, and a prerequisite:** the team (`7JL9RZ9C8P`) has **no Developer ID Application
  certificate**, found 2026-09-29 while running ADR-0136's spike: only Apple Development and Apple
  Distribution. Only the account holder can create one, in the developer portal, and nothing in this
  ADR can ship without it.
- **Follow-up:** the macOS install panel (ADR-0095) leads with the Familiar Server download once a
  notarized build exists.
