# ADR-0182: A Weekly Digest Notification, Sent by One Device

Status: proposed

Date: 2026-11-14

Extends [ADR-0179](ADR-0179-each-profile-has-a-whats-new-list-and-the-server-records-how-far-it-has-looked.md)
and [ADR-0181](ADR-0181-the-apps-show-whats-new.md)

Built last, after ADR-0179, ADR-0181 and ADR-0180.

## Context

The listener asked to be reminded even when not in the app, and chose a weekly digest over a
notification per release: "4 new releases, including X and Y" once a week.

What the apps have:

- **The Mac posts local notifications already.** Bandcamp imports use `UNUserNotificationCenter`
  with provisional authorization, so nothing prompts (`familiar-apple`
  `App/Shared/LibraryAdditions.swift:173-185`). No notification delegate exists, so tapping one does
  nothing in particular.
- **The iPhone wakes about hourly in the background.** A `BGAppRefreshTask`
  (`com.familiar.player.refresh`, `BackgroundRefresh.swift`) refreshes contract, favourites and
  caches. iOS decides when, and may skip it (after a force-quit, in Low Power Mode).
- **There are no remote notifications.** Neither app has the `aps-environment` entitlement, and the
  server cannot reach a device.

Two devices on one profile, each deciding on its own, would both notify.

## Decision

1. **The apps post local notifications.** No push service and no Apple Push Notification setup.
   The iPhone checks during its background refresh; the Mac checks at launch and hourly while
   running.

2. **The server decides which device sends a given week's digest.**
   `POST /api/v1/library/discover/whats-new/digest-claim` with `{min_interval_days: 7}` runs one
   atomic update on ADR-0179's `profile_discovery_state`:
   `… WHERE digest_sent_at IS NULL OR digest_sent_at < now() - interval … RETURNING`.
   - It counts items found after both `seen_through` and `digest_through`.
   - With nothing new, it claims nothing.
   - Otherwise it returns `{claimed, count, headline}`, where `headline` is up to two artist or
     release names, and advances `digest_through`.
   - The first device to claim notifies. Any other device gets nothing to post.

3. **The device decides when to try, as a pure function.** `DigestDecision` in FamiliarKit allows
   an attempt only between 09:00 and 21:00 local time, at least 12 hours after its last attempt,
   with the reminder on and notifications authorised. `digestBody` words it for one, two and many.
   The timing works however irregularly iOS runs the background refresh, because it is decided
   from stored dates, not from the refresh's schedule.

4. **Quiet by default, explicit when asked.** The app requests provisional authorization, so
   digests arrive quietly in Notification Center without a prompt. A setting, "Weekly new-release
   reminder", turns it off per server; turning it on explicitly asks for full authorization. A
   device with it off never claims.

5. **Tapping opens Discover.** A `UNUserNotificationCenterDelegate` reads `{host, destination:
   discover}` from the notification and routes there. It must leave the Bandcamp import
   notifications behaving as they do now.

## Alternatives Considered

**Remote push from the server.** Arrives on time even when iOS skips background refresh. Rejected: a
self-hosted server cannot hold Apple push credentials, and relaying through a service of ours would
mean every listener's server talking to us. Familiar has none of that, deliberately.

**A notification per release.** The most immediate. Rejected by the listener, and rightly: a
library of a few hundred artists finds several releases a week, and per-release alerts would be
switched off within a fortnight.

**Each device decides alone, with no claim.** No new endpoint. Rejected: a profile on a Mac and an
iPhone would get every digest twice, and the duplicate is what makes people turn reminders off.

## Consequences

- **Positive:** one quiet reminder a week, on whichever device got there first, that opens
  Discover.
- **Tradeoff:** delivery depends on iOS running the background refresh or the Mac app running; a
  week can be missed or arrive late.
- **Tradeoff:** a claim made by a device that then fails to post (permission revoked, a crash) uses
  up that week. Accepted rather than adding an acknowledgement round trip.
- **Follow-up:** whether the web admin should offer a digest too, for listeners without the apps.
