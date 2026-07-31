# ADR-0011: The Library Is Cached Whole, and Refreshed by Delta

Status: proposed

Date: 2026-07-31

Extends [ADR-0009](ADR-0009-offline-downloads-are-background-transfers.md)

## Context

[ADR-0009](ADR-0009-offline-downloads-are-background-transfers.md) point 9 limited offline browse to
the downloads list and explicitly deferred this decision. Deferring it leaves downloads as half a
feature: `App/Shared/LibraryStore.swift` pages from the server on every view, so with no network the
Apple client can play what it has downloaded but cannot navigate to it the way it was found. ADR-0009
also named this as the decision that settles whether its `Codable` index becomes SQLite, which is
why it wants deciding before that index acquires dependents.

Everything below was measured against the live library rather than estimated, and re-measured on
2026-07-31 before proposing.

| Fact | Value |
|---|---|
| Tracks | 26,396 active (26,462 rows, 66 inactive) |
| Full `TrackResponse` | 499 B/track → **13.2 MB** for the library |
| Ten-field browse subset | 271 B/track → 7.1 MB |
| Requests at the endpoint's `page_size` cap of 200 | **132** |
| Albums | 3,925 from `/library/albums`, 3,871 from `/library/stats` |
| Artists | 3,475 from `/library/artists`, 3,662 from `/library/stats` |
| `tracks.updated_at` churn | 510 rows in 24 h, 580 in 30 days, 52 distinct update days |

**The precedent for this was broken, and finding that out is what this ADR is for — but the bug
itself has since been fixed, so read it as history rather than as a live defect.** When this was
drafted on 2026-07-29, `services/libraryCache.ts` requested the library like this:

```ts
const { data } = await api.get('/tracks', { params: { limit: 10000 } });
```

`limit` is not a parameter of that endpoint. `page_size` is, capped at `le=200`
(`backend/app/api/routes/tracks/listing.py:298`), and FastAPI ignores unrecognised query parameters,
so the default page size applied: `GET /api/v1/tracks?limit=10000` returned **50 items** with
`page_size: 50` and `total: 26396`. The "cache library for offline browsing" action had been caching
**50 tracks of 26,396**, and nothing caught it because a 50-track offline library looks like a
feature that works rather than one that is broken.

It was fixed independently on 2026-07-30 (`5d7d1fb`, "cache the whole library, not the first page of
it", #46): the service now pages at 200 with a runaway guard, fails rather than returning a partial
cache, and carries a test asserting a cache larger than one page.

**The lesson survives the fix, which is why this stays in the record.** The argument for writing this
ADR was never "the web client has a bug" — it was that porting that design to Swift would have
ported the *shape* of the defect, and a cache that silently holds part of a collection is
indistinguishable from a working one. That is the same failure mode
[ADR-0012](ADR-0012-favorites-are-a-collection-not-a-library-section.md) point 3 rejects for
favourites, and the reason decision point 1 below caches the library whole rather than a working set.
What the fix removes is the *urgency*, not the reasoning: the web client's cache is now a flat track
list with no albums, no artists, no fingerprint and no refresh path beyond clear-and-refetch, and
those absences are what the decisions below are actually about.

**There is no delta endpoint, and `updated_at` is not yet a usable cursor.** `list_tracks` takes no
`since` parameter and `TrackResponse` does not expose `updated_at`, so a full 132-request re-fetch is
the only refresh available today. The column itself is promising — `tracks.updated_at` carries
`onupdate=func.now()` (`backend/app/db/models/tracks.py:112-114`) and its churn is low: 510 rows moved
in the last 24 hours and 580 in 30 days, so a delta would carry hundreds of rows instead of 26,396.
But the scanner's bulk upsert lists 23 columns explicitly in its `set_` clause and `updated_at` is
not among them (`backend/app/services/scanner.py:721-744`), and SQLAlchemy does not apply column
`onupdate` defaults to an `on_conflict_do_update` `set_` clause. So a rescan that changes a track's
tags leaves the timestamp untouched: the cursor is unreliable in exactly the direction that matters
most, and it is cheap to fix.

**`/library/stats` cannot serve as the staleness fingerprint**, which is the obvious thing to reach
for and the reason to look closely. It counts every `Track` row (`library.py:50-59`) while `/tracks`
applies `Track.active_filter()` — 26,462 against 26,396, which is the 66 inactive rows exactly. Its
`total_albums` is `COUNT(DISTINCT Track.album)` at 3,871 while `/library/albums` groups and reports
3,925; its `total_artists` is `COUNT(DISTINCT Track.artist)` at 3,662 while `/library/artists` reads
the artists table and reports 3,475. That is three notions of "how many albums" and two of "how many
tracks", none of them the set a client pages through. A fingerprint measuring a different set than
the data it guards reports false staleness, and — worse, because it is silent — false freshness.

**Albums and artists cannot be derived from cached tracks.** Artists are a real table with ids and
enrichment no client can compute: `image_url` on `/library/artists` is an external URL, Wikipedia in
the live data. Albums have no id at all — they are grouped server-side and keyed by name plus artist.
Deriving either on the device means a second implementation of grouping that has to agree with the
server's, which is the drift [ADR-0006](ADR-0006-offline-ranking-is-precomputed-server-side.md)
exists to prevent.

**Search, by contrast, is genuinely reproducible.** The server's is a case-insensitive substring
match across exactly three columns — `Track.title.ilike | Track.artist.ilike | Track.album.ilike`
(`listing.py:88-90`) — with no ranking and no relevance ordering. A local scan over the same three
fields is not an approximation of it; it is the same predicate. This is the distinction ADR-0006 turns
on: reimplementing a *scoring function* on four clients guarantees drift, while reimplementing
`contains` does not.

## Decision

The client caches the library whole, refreshes it by delta, and never derives what the server groups.

1. **The whole library is cached, not a working set.** 13.2 MB and 132 requests against a 26,396-track
   library, once. A working-set cache would need an eviction policy, a prefetch heuristic, and a
   story for what happens when the listener scrolls past its edge offline — all to save single-digit
   megabytes.

2. **Cache `TrackResponse` as generated, not a hand-picked projection.** The ten-field subset the web
   client keeps saves 6.0 MB and costs a running decision about which fields matter; ADR-0007 makes
   the full type generated, so caching it whole means a schema change reaches the cache by
   recompiling rather than by remembering to add a field.

3. **Albums, artists and playlists are cached as the server returns them.** No client-side grouping,
   per the Context above. Note the asymmetry this creates: tracks, albums and artists are
   library-wide, while playlists are per-profile, so the cache has a library-scoped part and a
   profile-scoped part and switching profiles invalidates only the latter.

4. **Storage stays files, and stays out of SQLite — deliberately, and this is the answer ADR-0009
   deferred.** One atomically-written `Codable` file per collection, bulk-replaced on refresh. The
   decisive argument is the *write pattern*, not the row count: a library cache is replaced wholesale
   when a refresh completes, where ADR-0009's download index mutates per event. Bulk replace is the
   shape a whole-file rewrite is good at. Search is a linear scan in memory, which at 26k rows and a
   `contains` predicate needs no index.

5. **A purpose-built fingerprint endpoint decides whether to refresh** — active track count and
   `max(updated_at)` over the same filtered set the listing endpoint pages, so one request answers
   "is my cache stale". Explicitly not `/library/stats`, for the reasons in Context.

6. **Refresh is full the first time and delta afterwards**, once the backend carries it: expose
   `updated_at` on `TrackResponse`, add an `updated_since` parameter to `list_tracks`, and add
   `updated_at` to the scanner's upsert `set_` clause so a tag change actually moves it. Those are
   backend changes under [ADR-0007](ADR-0007-clients-are-generated-from-openapi.md) and are
   prerequisites for the delta, not follow-ups to it.

7. **The delta carries removals rather than needing a separate reconcile.** A cursor query cannot see
   a deleted row, but Familiar does not delete tracks — it sets `status` away from active, 66 rows
   today, and that is an ORM update which moves `updated_at`. So when `updated_since` is supplied the
   endpoint returns rows regardless of status, and the client drops any id that comes back
   non-active. This is why the fingerprint counts *active* tracks: it is the check that catches a
   drift this rule missed.

8. **Offline search is the same predicate, not a similar one:** case-insensitive substring over
   title, artist and album. Asserted by a test that runs the same inputs against both, so the two
   cannot drift apart quietly the way `parseKey` did across the TypeScript and Python
   implementations ADR-0006 records.

9. **A stale cache is labelled, never silently served as current.** The client shows when the library
   was last refreshed and that it is browsing a cached copy. ADR-0009 point 4 made the filesystem the
   truth for downloads; the equivalent here is that a cache which cannot be verified against the
   server says so.

## Alternatives Considered

- **Port `libraryCache.ts`'s design, now that its paging bug is fixed.** Rejected, and the fix is
  what makes this the honest version of the question — the design can now be judged on its merits
  rather than on a defect. Its cache is a flat track list with no albums, no artists, no fingerprint
  and no refresh path beyond clear-and-refetch, and its search is `toArray()` followed by a
  JavaScript filter over every row. The Apple client needs the grouped collections and a staleness
  check, and neither is something that design could grow without becoming this one.
- **Cache a working set — recently played, favourites, downloads and their albums.** Rejected. It
  trades 5–10 MB for an eviction policy, a prefetch heuristic and an "offline edge" the listener
  discovers by scrolling into it. The whole library costing 13.2 MB is what makes this easy, and that
  number was measured before choosing.
- **Derive albums and artists from cached tracks.** Rejected, per Context: artist enrichment is not
  derivable at all, albums have no id, and the grouping would be a second implementation that must
  agree with the server's.
- **SQLite (or Core Data) for the cache.** Rejected at this size, and the reasoning is the write
  pattern rather than the row count — bulk replacement suits a file, incremental querying suits a
  database. It becomes correct if the cache later needs partial updates in place, per-field indexes,
  or to outgrow memory; ADR-0009 already names SQLite as the successor and this is the decision that
  keeps it a successor rather than a rewrite.
- **`/library/stats` as the fingerprint.** Rejected on measurement: it counts a different set than
  the endpoint it would guard, and the discrepancy is not theoretical — 26,462 against 26,396, 3,871
  against 3,925, 3,662 against 3,475.
- **Refresh on a timer and skip the fingerprint.** Rejected. It re-fetches 12.5 MB to discover
  nothing changed, and on cellular that is the kind of background cost that gets an app deleted.
- **A server-pushed invalidation channel** (SSE, or piggybacking the existing streams). Rejected as
  disproportionate for a library that changes on 52 days out of a 175-day history. A one-request
  fingerprint check at launch answers the same question without a connection to maintain.
- **Full-text search via SQLite FTS.** Rejected. The server's search is `ILIKE '%q%'` over three
  columns; matching it exactly is the goal, and FTS would give *better* results than the server,
  which is a divergence in the same family as a worse one.

## Consequences

- **Positive:** Offline browse becomes real rather than nominal, and the downloads ADR-0009 delivers
  become reachable through the same navigation used online.
- **Positive:** Both clients will cache the whole library rather than a page of it. That was the gap
  this ADR was written to stop the Swift client inheriting; the web half of it closed independently
  in #46, which is the outcome the ADR wanted and not evidence it was unnecessary.
- **Positive:** The delta cursor makes an ordinary refresh hundreds of rows rather than 26,396 —
  measured at 510 rows over the last 24 hours and 580 over 30 days.
- **Positive:** ADR-0009's storage question is answered with a reason, so the download index and the
  library cache stay one mechanism instead of two.
- **Tradeoff:** Three backend changes are prerequisites, not optional: `updated_at` exposed on
  `TrackResponse`, `updated_since` on the listing endpoint, and `updated_at` added to the scanner's
  upsert. The last is a correctness fix the web client also benefits from and nobody has needed until
  now.
- **Tradeoff:** The cache holds the full `TrackResponse`, so it grows with the schema. A field added
  for one client's benefit costs every cached row on every client.
- **Tradeoff:** Holding the library in memory is 13.2 MB as JSON but more once decoded into Swift
  strings, and the iOS floor is a 15.0-era device. That footprint should be measured before shipping,
  not assumed comfortable.
- **Tradeoff:** A profile-scoped part and a library-scoped part in one cache is a distinction that
  invites bugs at profile switch, in the same family as the pinned/cached distinction
  [ADR-0010](ADR-0010-played-bytes-are-cached-downloads-are-pinned.md) introduces.
- **Follow-up:** Measure the decoded in-memory footprint of 26,396 cached tracks on an iOS 15-era
  device, and revisit decision point 4 if it is uncomfortable.
- **Follow-up:** Decide whether artwork for cached albums and artists is fetched eagerly, lazily, or
  not at all offline. ADR-0009 already carries the equivalent question for track artwork; the answers
  should match.
- **Follow-up:** Decide whether the fingerprint endpoint also covers albums, artists and playlists,
  or whether their staleness rides on the track cursor. Grouping changes when a track's tags change,
  so it probably rides — but that should be asserted, since an album renamed with no track edit would
  slip through.
