# ADR-0180: New Releases by Similar Artists Are Found in the Background

Status: accepted

Date: 2026-11-14

Extends [ADR-0179](ADR-0179-each-profile-has-a-whats-new-list-and-the-server-records-how-far-it-has-looked.md),
[ADR-0099](ADR-0099-discovery-is-a-background-job-with-visible-sources.md) and
[ADR-0101](ADR-0101-discovery-ranks-against-the-listening-model.md)

Built third, after ADR-0179 and ADR-0181.

## Context

The listener asked to hear about new releases by artists *like* the ones he plays, not only by
artists already in the library. Nothing finds those today:

- **New-release discovery covers library artists only.** Both sources (MusicBrainz per artist,
  ListenBrainz `fresh-releases`) are matched against artists the library holds.
- **"Albums you might want" finds back catalogue, not new music.** It takes five seed artists, five
  Last.fm similar artists each and two MusicBrainz albums each, over a ten-year window
  (`services/recommendations.py:39-44`), and its rows are not per profile (ADR-0179 Context).
- **Similar artists are only fetched on a request.** `Artist.similar_artists` is filled by
  `GET /library/discover` calling Last.fm when it is missing (`api/routes/library_discover.py:138-150`),
  against ADR-0099 point 1. No background job warms it.
- **The ListenBrainz feed already holds the candidates.** `fresh-releases` returns every release of
  the last 30 days (`DEFAULT_DAYS = 30`, `services/discovery/listenbrainz.py:44`) with artist MBIDs,
  and is fetched every three hours. Today the job keeps only the releases whose artists are in the
  library and drops the rest.

## Decision

1. **A background job warms similar artists.** `similar_artists_warm` runs every six hours, makes at
   most 25 Last.fm calls, and fills `Artist.similar_artists` for each profile's most-played
   artists. Once it has run, the request path never needs to call Last.fm.

2. **Each profile has a similar-artist set.** Take its 25 most-played artists by
   `ProfilePlayHistory`, then the first ten of each one's cached similar artists with
   `match ≥ 0.3`, and drop any artist already in the library (by `ArtistAlias`).

3. **Similar artists are matched by MusicBrainz id, with names checked.** The id comes from Last.fm's
   `mbid` when present, then `ArtistCheckCache`, then a MusicBrainz search, at most 20 searches a
   run, accepted only with score ≥ 80 and a matching normalised name. Last.fm's `mbid` is often
   empty or wrong, so a name check guards every source.

4. **The ListenBrainz feed already fetched is matched a second time.** A second pure selector,
   `select_for_similar(releases, similar_mbids)`, runs over the same response in
   `tasks/listenbrainz_releases.py`. No extra request is made.

5. **Storage keeps releases library-wide and reasons per profile.** Releases go in
   `external_album_cache` with `discovery_context = 'similar_artist_new_release'`, under their own
   partial unique index on `release_id`, as each context has. A new table,
   `profile_release_reasons(external_album_id, profile_id, seed_artist_id, seed_artist_name,
   match_score, created_at)`, unique on `(external_album_id, profile_id)`, records why each profile
   gets each release, keeping the best match. A similar-artist release appears only for profiles
   with a reason row.

6. **The reason is the played artist.** ADR-0179's item reads `kind = similar_artist` and
   "Similar to X, which you play". This is narrower than ADR-0101 point 3's "real pair of tracks":
   the listener owns no track by the new artist, so there is no pair to show. The played artist
   and Last.fm's match are the honest reason.

7. **Only genuinely new releases count as new.** A release counts as new only if its
   `release_date` is within 14 days of `discovered_at`, so the job's first run does not announce a
   month of releases at once.

8. **ADR-0099's gates and health apply.** The job runs only with `discovery_enabled` and both
   `source_enabled("listenbrainz")` and `source_enabled("lastfm")`, reports through the health
   recorder (points 6 and 10), and after inserting, sends each affected profile ADR-0179's
   `whats_new_changed` notice.

## Alternatives Considered

**Check every similar artist against MusicBrainz, as library artists are.** More complete: it would
catch releases ListenBrainz does not list. Rejected for now: 25 played artists × 10 similar is up
to 250 artists, at MusicBrainz's one request a second, on top of the library batch that already
uses the budget. The ListenBrainz feed is free because it is already fetched.

**Extend "Albums you might want" to recent releases.** Its pipeline already walks similar artists.
Rejected: its rows are not per profile, the last profile refreshed overwrites the others, and its
ten-year window and ranking are built for back catalogue. Fixing it is a separate decision.

**Store the reason on the release row.** One column instead of a table. Rejected: two profiles reach
the same release from different played artists, and a single column would show one profile the
other's reason.

## Consequences

- **Positive:** new music beyond the library, each release with a reason the listener recognises.
- **Positive:** the request path stops calling Last.fm once the warmer has run, closing an
  ADR-0099 point 1 breach.
- **Tradeoff:** releases that ListenBrainz does not list are missed: small or Bandcamp-only
  artists, and anything outside its 30-day window. The empty state says so.
- **Tradeoff:** if ListenBrainz is down for more than 30 days, the releases from that gap are not
  recovered; health reports the outage.
- **Follow-up:** whether to check a bounded number of similar artists against MusicBrainz too,
  once the budget is measured.
