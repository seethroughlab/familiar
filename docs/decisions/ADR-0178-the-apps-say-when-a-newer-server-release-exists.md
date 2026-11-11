# ADR-0178: The Apps Say When a Newer Server Release Exists

Status: accepted

Date: 2026-11-11

Implementation:

- **Server, points 2–4, 2026-11-11 (#485).** `DEFAULT_UPDATE_CHANNEL = "beta"` in
  `app/services/app_settings.py`. `_migrate_update_channel` runs in `_load`: a file without
  `update_channel_migrated` whose channel is `"disabled"` or missing becomes `"beta"`, is saved, and
  is logged with where to turn it off. Every file gets the marker, so it runs once. The marker
  defaults to `True`, so a new install never migrates, and `get_masked` drops it.
  `SettingsResponse` lists its fields, so the API schema did not change. `scripts/deploy-dev.sh`
  writes `dev` to the container's `/app/VERSION`. Tests: `tests/test_update_channel_default.py`.
  Four fail against the previous settings code; the other four guard that a channel someone chose
  is kept. `docs/CONFIGURATION.md` gains "Update checks".
- **Not done:** point 5, the banner in `familiar-apple`.

Extends [ADR-0168](ADR-0168-a-server-names-what-it-can-do.md) and
[ADR-0113](ADR-0113-the-api-declares-a-contract-version.md)

## Context

A listener whose server is behind finds out only by accident. ADR-0168 lets the iPhone and Mac apps
say that a server *lacks a feature the app offers* ("Lyrics need a newer server"). That fires only
when an app is newer than its server, and only for a feature with a capability name. Nothing says
that a newer server release *exists*. ADR-0176 Phase 4 made this matter: once a server enforces
media credentials, the safe order is apps first, then the server. And how the server updates
depends on its form:

- **Docker** never updates itself. No compose file runs Watchtower or anything like it; the owner
  runs `./update.sh` (`docs/INSTALLATION.md`).
- **Familiar Server** (the Mac app) checks its Sparkle feed itself (`SUEnableAutomaticChecks` in
  `desktop/macos/Support/Info.plist`) and asks before installing.

The server already knows how to find out. `app/services/update_checker.py` reads GitHub's releases
API, compares the release tags with `get_app_version()` and caches the answer for a day. It runs
30 seconds after startup and daily at 03:30 (`background/manager.py`, job `daily_update_check`).
`GET /api/v1/updates` (`system_get_update_status`) returns that cached answer. The web admin shows a
toast from it (`hooks/useUpdateNotification.ts`) and a status block under Server
(`panels/server/SystemStatus.tsx`).

**It almost never runs.** `AppSettings.update_channel` defaults to `"disabled"`
(`app/services/app_settings.py:131`), and every release so far is a beta, which the `stable`
channel skips (`_matches_channel`). Three facts verified while writing this:

- **Changing the default would not reach existing servers.** `_save` writes `model_dump()`, every
  field and its default. The NAS's `data/settings.json` holds `"update_channel": "disabled"`,
  although nobody chose it there.
- **The version string lies on a hand-deployed server.** On 2026-11-11 the NAS reported
  `v0.2.0-beta22`: the image is beta22, and `make deploy-dev` overlays newer code without touching
  `/app/VERSION`. With the check on, it would have announced beta24 to a server running code newer
  than beta24. ADR-0168's Context found the same problem on the demo (`"demo"`) and on development
  servers (`"dev"`). The checker already skips `"dev"`, and `"demo"` does not parse as a version,
  so both answer "no update".
- **The Apple client cannot ask yet.** `system_get_update_status` is not in `familiar-apple`'s
  generated surface (`Sources/FamiliarAPI/openapi-generator-config.yaml`), and nothing in the app
  reads `update_available`.

## Decision

1. **The server stays the one place that asks GitHub.** The apps read its cached
   `GET /api/v1/updates`, which needs the token as before. No app contacts GitHub, and no app
   compares version strings itself.

2. **The check is on by default.** `update_channel` defaults to `"beta"` while every release is a
   beta, and to `"stable"` once a stable release exists. One outbound request to `api.github.com` a
   day is the cost; it is stated in `docs/CONFIGURATION.md` and in the release notes, and
   `"disabled"` still turns it off.

3. **A stored `"disabled"` that nobody chose is migrated once.** `settings.json` cannot tell a
   choice from a saved default, so the release that ships this rewrites `"disabled"` to the
   default's channel exactly once, records that it did (`update_channel_migrated: true`), and logs
   it. The release notes say how to turn it back off. A server whose owner turns it off after that
   stays off.

4. **A server only announces an update when it knows its own version.** `make deploy-dev` writes
   `dev` into the container's `/app/VERSION`, so a hand-deployed server skips the check instead of
   announcing a release older than its code. `"demo"` keeps failing to parse, so App Review never
   sees the banner.

5. **The apps show it once, quietly, where the other server banners are.** In `LibraryView`, beside
   ADR-0113's and ADR-0168's `ServerBehindBanner`, and below them in priority: a server that cannot
   do something the app needs says that first. The words are "Familiar server 0.2.0-beta25 is
   available. This server runs 0.2.0-beta24.", with release notes from `release_url`. It can be
   dismissed, and the dismissal is kept per server and per `latest_version`, so the next release
   shows it again. The decision is a pure function in `FamiliarKit`, as `ServerCapabilities` is.

6. **The web admin keeps its toast and status block**; with point 2 they start working.

## Alternatives Considered

**Each app asks GitHub itself.** It would work with the server's check off. Rejected: every phone
and Mac would contact GitHub, and the app would have to compare the server's version string, which
point 4 and ADR-0168 show is wrong on the NAS, the demo and development servers.

**Each app knows from its own build.** Each app release would carry the newest server release it
knows, compared with a release number in server source, with no network call at all. Rejected
because it only knows about server releases older than the app: a server release between two app
releases, the usual case, would go unannounced.

**Turn the default on for new installs only.** It respects every stored `"disabled"`. Rejected
because that is every existing server, including all of today's users, and the stored value
records no choice (Context).

**Show it as a blocking alert.** Rejected for ADR-0113 point 8's reason: an older server still
works, and the listener cannot act on it from a phone mid-song.

## Consequences

- **Positive:** a listener hears about a server release in the app they use, without the server's
  owner opening the web admin.
- **Positive:** one outbound check per server, not per device, and the apps learn nothing they
  could not already ask the server.
- **Tradeoff:** every server now contacts `api.github.com` daily unless turned off, which is a
  change from today's silence, and the migration turns it on for servers whose stored `"disabled"`
  may have been deliberate.
- **Tradeoff:** it starts with the server release that ships points 2–4. A server older than that
  keeps reporting no update, so the apps' banner reaches the people who need it most only after
  one more upgrade they make unprompted.
- **Follow-up:** whether the banner should say *how* to update for the server's form (Familiar
  Server updates itself through Sparkle; Docker runs `./update.sh`). The server does not report its
  form today.
