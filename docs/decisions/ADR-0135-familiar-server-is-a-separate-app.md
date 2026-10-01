# ADR-0135: Familiar Server Is a Separate App Distributed with Developer ID

Status: accepted

Date: 2026-09-29

Implementation:
- **Accepted 2026-09-30**, as written, with its certificate follow-up corrected (below).
- **Point 1 built 2026-09-30.** `scripts/build-app.sh` gives every signature a secure timestamp when
  the identity is a Developer ID; `scripts/package.sh` makes the `.dmg` (APFS, ULFO), signs it,
  notarizes it with the App Store Connect API key familiar-apple's uploads already use, staples it,
  and fails unless Gatekeeper assesses the app inside as `Notarized Developer ID`. Proved on
  `v0.2.0-beta7`'s code: 922 MB app, 426 MB `.dmg`, **accepted on the first submission**; Apple's log
  has ten warnings, all gzipped pickles in joblib's own test data that it cannot unpack as archives.
  The integration check passes with the app signed by the Developer ID, not only Apple Development.
- **Point 2 built 2026-09-30:** the `familiar-server` job in `.github/workflows/release.yml`, on the
  self-hosted Mac, after `create-release`, attaching the `.dmg` to it — so a sleeping laptop delays
  the download and never the image. It imports the certificate into a keychain of its own. Secrets:
  `DEVELOPER_ID_P12` (base64), `DEVELOPER_ID_P12_PASSWORD`, and the notary key under
  familiar-apple's names, `FAMILIAR_ASC_KEY_ID`, `FAMILIAR_ASC_ISSUER_ID`,
  `FAMILIAR_ASC_PRIVATE_KEY`.
- **Found building it: the payload's version must be the tag.** The backend fetches its CLAP
  encoders from the release named by its version (ADR-0132 point 8), and the image is given the tag,
  `v` and all. A first draft passed the version without the `v`, and the server asked for
  `/releases/download/0.2.0-beta7/…`, which cannot exist. The scripts now take the tag and drop the
  `v` only for `CFBundleShortVersionString` and the file name; `build-payload.sh` refuses anything
  else. No release yet carries the encoders — #343 merged after `v0.2.0-beta7` — so the first Mac
  server that can fetch them is the next release's.
- **First release, `v0.2.0-beta8`, 2026-10-01: the `.dmg` shipped on the third run of the job.** The
  first failed at the import: `DEVELOPER_ID_P12_PASSWORD` had been set through a shell with no
  terminal, so `gh` stored an empty value, and the job's own check caught it. The second failed in
  ffmpeg's configure, probing x86 assembly: **the self-hosted Mac's runner was GitHub's x86_64
  build under Rosetta**, so every job it ran built for Intel, familiar-apple's included. The runner
  was swapped to the `osx-arm64` package of the same version (registration kept, the x86_64
  binaries left beside it), and the build scripts now re-run themselves natively if started under
  Rosetta. The released `.dmg` (371 MB) assesses as `Notarized Developer ID` after a quarantined
  download, and every one of its 416 libraries and executables carries arm64.
- **Point 5 built 2026-10-01.** The menu offers "Get Familiar for Mac…" (the Mac App Store app)
  and "Get Familiar for iPhone…" (the store page, to share to a phone) from the first run on.
  "Open in Familiar" appears only when some app handles `familiar://`; before, with no player
  installed, it opened a link nothing received and did nothing. `PlayerLinks` is tested against the
  App Store id the site links, which `check-claims` checks against the live store.
- **Not built:** point 3 (Sparkle), so an update is a new download until it is.

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
- **Follow-up, and a prerequisite, found to be already met:** this said the team (`7JL9RZ9C8P`)
  had no Developer ID Application certificate. It had one, issued 2026-03-06, in the login keychain
  of the Mac that runs the macOS CI jobs; nobody had looked for it by name. It **expires 2027-02-01**
  — issued under Apple's original Developer ID intermediate, which expires that day — so a
  replacement is needed before the first release after it. What is already notarized keeps working;
  only new signatures stop.
- **Follow-up:** the macOS install panel (ADR-0095) leads with the Familiar Server download once a
  notarized build exists.
