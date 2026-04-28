# Canonical Artists — Migration Plan

A plan to replace ad-hoc string-grouping of `tracks.artist` with a real
artist data model. Closes the duplicate-tile class of bugs (Beatles ×3,
ANOHNI/Antony ×3, Ceephax ×2, "X & Y" collaborations, etc.) and gives
per-artist features (favorites, listening stats, follow-for-new-releases)
a stable id to hang off.

## The problem we're fixing

Today, `tracks.artist` is a free-text column. Every code path that asks
"what artists does the user have?" answers it the same way:

```sql
SELECT lower(trim(artist)) AS norm, max(artist), count(*)
FROM tracks
GROUP BY lower(trim(artist));
```

This treats every distinct *spelling* of an artist tag as a distinct
artist. From the live library:

| Tag string | Tracks | Real artist |
|---|---|---|
| `Beatles` | 193 | The Beatles |
| `Beatles, The` | 27 | The Beatles |
| `The Beatles` | 90 | The Beatles |
| `ANOHNI and the Johnsons` | 1 | Antony Hegarty / ANOHNI |
| `Antony` | 1 | Antony Hegarty / ANOHNI |
| `Antony And The Johnsons` | 18 | Antony Hegarty / ANOHNI |
| `Ceephax` | n | Ceephax Acid Crew |
| `Ceephax Acid Crew` | n | Ceephax Acid Crew |
| `Brian Eno` | n | Brian Eno |
| `Brian Eno & David Byrne` | n | Brian Eno + David Byrne (collab) |

The follow-on effects show up everywhere:

- Artist tile grid shows duplicates and triplicates.
- Per-artist stats split across name variants.
- `artist_info` cache (Last.fm bio, similar artists, image) keyed by
  normalized name → same artist gets fetched 3× and stored 3×.
- Image resolver attaches a "primary artist" photo to collab entries
  via `_split_compound_artist`, leaving multiple library entries
  sharing one photo.
- New-releases polling double-counts the same MusicBrainz artist.

The proper fix is a one-time data normalization, not another runtime
heuristic layer.

## Target data model

```
artists
  id              uuid pk
  name            text       -- canonical display name ("The Beatles")
  sort_name       text       -- "Beatles, The" — used for ordering
  musicbrainz_id  text null  -- canonical MB artist UUID
  image_url       text null  -- resolved Wikipedia/Wikidata/Spotify thumb
  image_checked_at timestamp null
  bio_summary     text null
  bio_content     text null
  lastfm_url      text null
  listeners       int null
  playcount       bigint null
  similar_artists jsonb default '[]'
  tags            jsonb default '[]'
  fetched_at      timestamp default now()
  created_at      timestamp default now()

artist_aliases
  alias_normalized text pk    -- normalize(alias)
  alias            text       -- as it appears in tags
  artist_id        uuid fk → artists.id
  source           text       -- 'tag', 'mb', 'manual_merge'

track_artists
  track_id        uuid fk → tracks.id
  artist_id       uuid fk → artists.id
  role            text default 'primary'  -- 'primary' | 'feat' | 'with'
  position        int        -- for collab ordering
  pk (track_id, artist_id)
```

`tracks.artist` (the original tag string) stays for forensics, but
becomes read-only after migration. All artist queries go through
`artists` + `track_artists`.

## Mapping rules (alias → canonical artist)

In order, at scan time:

1. **MusicBrainz artist ID match.** If the track tag carries a MBID
   (`Track.musicbrainz_artist_id`), look up an artist with that
   `musicbrainz_id`. Match → done.
2. **Existing alias hit.** Normalize the tag string and look up
   `artist_aliases.alias_normalized`. Match → done.
3. **MusicBrainz lookup.** Run `_strict_mb_artist_lookup(name)` (the
   existing strict-name resolver). Hit → create or find an
   `artists` row for that MBID, register the tag string as an alias.
4. **Last fallback.** Create a new `artists` row using the tag string
   as canonical name, no MBID. The user can merge later.

For collaborations (`"Brian Eno & David Byrne"`, `"X feat. Y"`), use
the existing `_split_compound_artist` to extract members. Each member
gets its own `track_artists` row (`role='primary'` for first, `'with'`
or `'feat'` for the rest). The full collab string still becomes an
alias for the first member's canonical artist (so legacy lookups don't
break), but the artist tile grid shows individual artists, not collabs.

## Migration steps

### 1. Schema migration (one Alembic file)

- Create `artists`, `artist_aliases`, `track_artists` tables.
- Add `tracks.canonical_artist_id` (denorm of primary artist for fast
  filtering) — nullable initially.
- Don't drop anything yet.

### 2. Backfill job (one-shot)

A management command (`backend/app/cli/backfill_artists.py`):

1. Pull all distinct `(lower(trim(artist)), musicbrainz_artist_id)`
   pairs from `tracks`.
2. Group by MBID where present. Each MBID → one `artists` row.
3. For tag strings without MBIDs, run `_strict_mb_artist_lookup` (rate
   limited to 1 RPS — same as existing MB calls). Match → attach to
   existing artist row by MBID. Miss → create a standalone artist
   row.
4. Populate `artist_aliases` for every distinct tag string.
5. Migrate existing `artist_info` rows into `artists` (preserve
   `image_url`, bio, similar, etc.) — keyed by normalized alias.
6. Populate `track_artists` from each track's tag string by splitting
   compounds via `_split_compound_artist`.
7. Set `tracks.canonical_artist_id` to the primary collaborator.

Expected runtime on a 23k-track / 3.5k-artist library: ~1 hour
(MB rate limit is the floor; ~1500 unknown-MBID artists × 1 sec
each).

### 3. Read-side cutover

Update endpoints to read from the new model:

- `library_artists.list_artists` → `SELECT FROM artists ORDER BY
  sort_name`. No more GROUP BY, no more runtime normalization.
- `library_artists.get_artist_detail` → lookup by `artists.id`.
- Frontend artist links switch from `/artists/{name}` to
  `/artists/{id}` (or keep slug routes that resolve to id).
- `recommendations.py`, `new_releases.py`, similar-artists, and the
  image resolver all key off `artist_id` instead of normalized name.

### 4. Write-side cutover

Scanner (`backend/app/services/scanner.py`):

- After parsing track tags, run the alias→artist resolution chain
  above before insert.
- Set `track.canonical_artist_id` and create `track_artists` rows.
- New aliases discovered during scan get added automatically.

### 5. Manual merge UI (one admin page)

Some duplicates won't auto-resolve (MB-untagged artists, typos, name
changes that MB doesn't surface). A simple admin page:

- List artists sorted by track count, with checkboxes.
- "Merge selected → canonical X" action: rewrites `track_artists`,
  moves aliases, deletes the source row.
- Optional: surface fuzzy candidates ("artists whose names are 90%
  similar") to suggest merges.

This is the long-tail cleanup tool — most merges happen automatically
via MB.

### 6. Drop the old column (optional, later)

Once the new model has been live for a week and nothing in the code
reads `tracks.artist` directly, the column can be dropped or kept
read-only as a forensics field. No rush.

## Phasing

The plan above is one continuous body of work but ships in two
deployable commits:

1. **Commit A (schema + backfill, dual-write):** schema, backfill
   command, scanner writes to both old and new model. Endpoints
   still read from the old GROUP BY. Behavior unchanged for users.
2. **Commit B (read cutover + admin UI):** endpoints switch to the
   new model. User now sees the deduped artist grid. Admin merge UI
   ships in the same commit so the user can clean up the long tail.

Old-column drop is a third, optional, much-later commit.

## Out of scope

- **Changing the `Track.artist` tag string itself** (we don't write to
  source files; canonical artist lives in the DB).
- **Smart playlist rewrite.** Smart playlists today filter by
  `Track.artist` strings. After cutover, `SmartPlaylistService` should
  resolve artist filters via aliases too — but that's a follow-up.
- **Multi-MBID merges.** If MB has the same artist under two MBIDs
  (does happen with renamed acts like Antony → ANOHNI), the manual
  merge UI handles it. Don't try to auto-detect.
