# ADR-0179: Each Profile Has a What's-New List, and the Server Records How Far It Has Looked

Status: accepted

Date: 2026-11-14

Implementation:

- **Points 1–7, 2026-11-14 (#488).** Migration `20261114_profile_discovery_state` and model
  `ProfileDiscoveryState` (`db/models/profiles.py`). `app/operations/whats_new.py` holds `get` and
  `mark_seen`. It lists `artist_new_release` rows that are not dismissed, not owned and released
  within 90 days (`RELEASE_WINDOW`), newest found first. The reason comes from this profile's plays,
  through `ArtistAlias.alias_normalized`, which uses the same normaliser as the cache's
  `artist_name_normalized`. The routes are in `api/routes/library_discover.py`, under the `discover`
  tag. `seen` updates with `GREATEST`, commits, and only then sends `WHATS_NEW_CHANGED`
  (`services/playback_commands.py`), so a device that refetches reads the new state. The MCP tool
  `get_whats_new` reads and never marks seen. `NewReleasesSection.tsx` posts the newest
  `discovered_at` it rendered, compared as instants (`newestDiscoveredAt`), because Python drops zero
  microseconds and the strings do not sort as text. Capability `discover.whats_new` is in
  `SERVER_CAPABILITIES` and recorded in `test_contract_lock.py`. Tests:
  `tests/test_whats_new.py`. App side: `familiar-apple` #274 (ADR-0181).

Extends [ADR-0099](ADR-0099-discovery-is-a-background-job-with-visible-sources.md) and
[ADR-0101](ADR-0101-discovery-ranks-against-the-listening-model.md)

The first of four: ADR-0179 to ADR-0182 make Familiar remind its listener to get new music. They
are built in this order: 0179, 0181, 0180, 0182. 0179 and 0181 together are the first slice, using
the releases the server already finds.

## Context

On 2026-11-14, while checking media credentials, the author opened Discover on the iPhone and found
he had forgotten it existed. Familiar already finds new music in the background, but nothing tells
the listener it did.

What is already found, and where:

- **New releases by library artists.** The `discovery_batch` job checks ten artists every 20
  minutes against MusicBrainz (`services/tasks/new_releases.py`, `_check_artist_against_musicbrainz`).
  ListenBrainz's `fresh-releases` feed is read every three hours
  (`services/discovery/listenbrainz.py`, `DEFAULT_DAYS = 30`). Both write `external_album_cache`
  rows with `discovery_context = 'artist_new_release'` and a `discovered_at` timestamp
  (`db/models/artists.py:226`). Both are behind `discovery_enabled` and the per-source flags
  (`services/discovery/sources.py:146`, ADR-0099 point 12).
- **`GET /api/v1/new-releases`** lists them with `as_of` and `age_hours` (ADR-0099 point 7). It is
  not in the Apple client's generated surface.

What is missing:

- **No per-profile record of what has been seen.** Without one, "new" can only mean "found
  recently", which shows the same releases for days and cannot clear when the listener has looked.
- **Dismissal is library-wide.** `ExternalAlbumCache.dismissed` and `dismissed_by_profile_id`
  (`db/models/artists.py:220`) hide a release from every profile.

Premises contradicted while checking, recorded so nobody re-derives them:

- **`GET /library/discover` still calls Last.fm on the request path** when an artist's
  `similar_artists` is not cached (`api/routes/library_discover.py:138-150`, `get_artist_info`),
  against ADR-0099 point 1. ADR-0180 adds the background warmer that removes the need.
- **"Albums you might want" is not per profile.** `listening_profile_recommendation` rows have no
  profile column. The nightly refresh runs every profile and prunes rows older than its own run for
  all of them (`services/recommendations.py:598-616`), so the last profile processed wins. Nothing
  here builds on that context.

## Decision

1. **The server holds each profile's what's-new list and its seen state.** A listener uses Mac,
   iPhone and the web Discover page under one profile, and looking at new releases on any of them
   must clear the reminder on all of them. App-side state cannot do that.

2. **A new table, `profile_discovery_state`**: `profile_id` (primary key, foreign key with cascade
   on delete), `seen_through`, `digest_through`, `digest_sent_at` and `created_at`, all naive UTC
   like `discovered_at`. The digest columns are ADR-0182's and are created now to avoid a second
   migration. The row is created on first read with `seen_through` set to the newest
   `discovered_at` already stored, so the backlog that exists today is never announced as new.

3. **`GET /api/v1/library/discover/whats-new?limit=20`** returns
   `{state, as_of, age_hours, seen_through, new_count, items[]}`.
   - `state` is `ok`, `never_run` or `disabled`. It is never collapsed into an empty list (ADR-0099
     point 8: "never run" is not "nothing new").
   - Each item is `{id, artist_name, release_name, release_type, release_date, artwork_url,
     discovered_at, is_new, bandcamp_url, external_url, reason}`, and
     `reason = {kind, text, seed_artist_name, play_count}`. The kind is `library_artist` here;
     ADR-0180 adds `similar_artist`. A release always says why it is listed (ADR-0101 point 3, in
     the narrower form ADR-0180 states).
   - Dismissed releases and releases already in the library are excluded.
   - Under the `discover` tag, which the Apple client already generates, so no generator or lint
     list changes.

4. **`POST /api/v1/library/discover/whats-new/seen` with `{through}`.** `through` is the newest
   `discovered_at` the client actually showed, never the current time, so a release found between
   the read and the write is not marked seen unread. `seen_through` only moves forward. After a
   change, the server sends the profile's attached clients the notice
   `{"type": "whats_new_changed"}` through `PlaybackCommandChannel.notify`, the ADR-0177 pattern,
   so another device clears its marker without waiting for its next refresh.

5. **The web Discover page marks what it shows as seen.** `NewReleasesSection.tsx` in `/embed` posts
   `seen` when its list has rendered. The embed sends the profile from its `?profile=` parameter
   as `X-Profile-ID` (`services/embedBridge.ts:64`), so the write lands on the right profile.

6. **The logic lives in `app/operations/whats_new.py`**, shared by the route and an MCP tool that
   answers "what's new for me" (ADR-0173). The request path reads stored rows only and never calls
   out (ADR-0099 point 1).

7. **The server advertises `discover.whats_new`** in `SERVER_CAPABILITIES` (ADR-0168). The
   schema change is additive (ADR-0113).

## Alternatives Considered

**Seen state in each app.** Each device would remember the newest release it had shown, as
ADR-0178 does for update notices. Rejected: the same profile on the Mac and the iPhone would
disagree, and opening Discover on the phone would leave the Mac's marker lit indefinitely. Update
notices could live on the device because they describe the server, not the listener.

**"New" means found in the last seven days.** No state at all. Rejected because it cannot clear:
the marker would stay on for a week after the listener had looked, which teaches them to ignore it.

**Per-profile columns on `external_album_cache`.** Rejected: the cache is deliberately one row per
release for the whole library (its partial unique indexes are on `release_id`), and the
recommendation context shows what goes wrong when profile-specific data is squeezed into it.

## Consequences

- **Positive:** one answer to "what's new for me" for every client, including the MCP endpoint.
- **Positive:** built on data the server already gathers; the first slice needs no new discovery.
- **Tradeoff:** a new table and two endpoints to keep, and `seen` is a write on an otherwise
  read-only surface.
- **Tradeoff:** dismissal stays library-wide. Per-profile dismissal is a separate decision, not
  taken here.
- **Follow-up:** ADR-0180 adds similar artists' releases; ADR-0181 shows the list in the apps;
  ADR-0182 sends the weekly digest.
