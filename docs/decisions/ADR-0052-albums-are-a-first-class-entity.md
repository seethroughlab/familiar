# ADR-0052: Albums Are a First-Class Entity

Status: proposed

Date: 2026-08-12

Extends [ADR-0051](ADR-0051-edited-metadata-outranks-file-tags.md)

## Context

Familiar has an `Artist` entity with canonical resolution
(`backend/app/db/models/artists.py`, `backend/app/services/artist_resolver.py:144`). It has never had
an `Album` one. An album is whatever a `GROUP BY` over tag strings says it is, computed fresh on
every request, and album artwork is filed under
`sha256(normalize_for_matching(track.artist) + "::" + normalize_for_matching(track.album))[:16]`
(`backend/app/services/artwork.py:73`).

The prompt was a defect in a feature that shipped the same day. The Mac's metadata editor now accepts
a dropped image, and its caption says the cover applies to the whole album. On **328 albums that is
false**, because the key uses `track.artist` and never `album_artist` — so a compilation, a record
with features, or anything whose track artists differ fragments into one artwork slot per artist
string. Dropping a cover changes the fraction of the album that happens to share one spelling.

Measured on the live library, 26,422 active tracks:

| | |
|---|---|
| Artwork slots today (`artist` + album) | **6,221** |
| Slots if keyed by `album_artist ?? artist` + album | 4,295 |
| Slots if keyed by **canonical artist id** + album | **3,908**, plus 372 folder-derived |
| Albums whose tracks carry more than one artist string | 328, occupying 2,425 slots |
| Tracks where `album_artist` differs from `artist` | 3,812 |
| Tracks with no album tag | 801, across 372 folders — today sharing **one** `unknown::unknown` slot |
| Artwork on disk | 12,017 files, 283 MB, including 1,119 `.generated` markers |

**6,221 buckets for roughly 3,900 records.** The redundancy is not only storage: art is fetched,
generated and stored more than once for one album, and `/artwork/regenerate-stale` walks the
duplicates too.

### Nothing owns the question

Six definitions of "the same album" exist in the backend, and no two agree at the edges:

| Where | Key |
|---|---|
| `library_albums.py:133` `list_albums` | `lower(album_artist_col), lower(album)` — **no `trim`** |
| `library_albums.py:189` `get_album_detail` | `lower(trim(...))` |
| `library_artists.py:457` artist detail | raw `Track.album`, case-sensitive |
| `embedding_map.py:526` `_aggregate_by_album` | Python `f"{artist} - {album}"` |
| `playlist_generation.py:232` | `f"{artist_key}:{album.lower().strip()}"` |
| `artwork.py:73` `compute_album_hash` | `normalize_for_matching` — quotes, dashes, diacritics, casefold |

The first two disagreeing is not theoretical: `GET /library/albums/{artist}/{album}` carries a
`?source=artist` query parameter whose only purpose is to tell the server which grouping the client
came from, because the album keys the two surfaces produce do not round-trip.

A seventh definition lives in the browser. `packages/frontend/src/utils/albumHash.ts` is a
hand-written JavaScript reimplementation of `normalize_for_matching` **and of SHA-256**, so the web
app can compute the server's artwork hash itself. Its own comments say it "must stay in sync with"
two Python modules, and concede the difference it cannot close — *"toLowerCase is close enough for
JS"*, where Python uses `casefold`.

### Why a better hash is not the answer

The obvious repair is to hash `album_artist ?? artist` instead. It would collapse 6,221 slots to
4,295 and fix the compilations. It would not be durable, and durability is the point: **any key
derived from attributes moves when the attributes move.** Renaming an album re-keys its artwork to a
slot nothing has ever fetched, so the cover silently disappears — and the editor that shipped this
week actively invites renaming albums.

[ADR-0051](ADR-0051-edited-metadata-outranks-file-tags.md) has just established that a person's
correction survives the file changing underneath it. Artwork must survive the same event, and a hash
of the corrected fields cannot.

### Why not the approaches other players use

Both were ruled out by measurement, not preference:

- **Folder as the album** (Jellyfin, Emby, beets, Kodi): **315 albums span more than one directory**
  in this library. Multi-disc sets would split into one album per disc.
- **A matched release id** (Plex, Roon): only **1,782 of 26,422 tracks — 6.7%** — carry a
  `musicbrainz_album_id`. It is authoritative where present and absent almost everywhere.

Both remain useful as *inputs* to identity. Neither can be identity on its own.

## Decision

1. **An album is an entity with a surrogate id.** A row in `albums`, not a hash and not a tuple of
   tags. Tag strings stay on `tracks` as forensics, exactly as `tracks.artist` did when artists became
   canonical.

2. **Identity resolves through a cascade**, in `backend/app/services/album_resolver.py`, which is the
   sole owner of the rule the way `resolve_canonical_artist` is for artists: a verified MusicBrainz
   release id → an alias hit → the containing folder when there is no album tag → create.

3. **Album identity inherits artist identity.** The alias key holds the canonical *artist id*, not an
   artist string. Merging two artists in the existing cleanup UI therefore merges their albums for
   free, and "Beatles / Revolver" and "The Beatles / Revolver" are one album without anybody saying
   so. Measured effect today is small — 3,921 pairs collapse to 3,908 — but it is the property that
   keeps paying as the artist table is cleaned up.

4. **Artwork is keyed by the album id.** `get_artwork_path` (`artwork.py:59`) takes an album id;
   `compute_album_hash` retires. Renaming an album then changes the row's matching inputs while its
   id stays put, so the cover follows the album.

5. **Tracks with no album tag group by their containing folder.** 372 folders become 372 albums,
   replacing a single shared `unknown::unknown` bucket that today would give one dropped cover to 61
   unrelated tracks. 97.5% of directories in this library hold exactly one album, so the folder is a
   good guess where there is nothing else to go on.

6. **The public API is unchanged by this ADR.** Albums stay addressed by artist and name; the id is a
   storage primitive. No OpenAPI regeneration and no Swift work — the Apple clients read artwork
   through `/tracks/{id}/artwork` and have never touched the hash. **The web app is not exempt**: it
   computes the key itself, so `albumHash.ts` is deleted and the client uses the keys the server
   already returns from `POST /artwork/queue/batch`.

7. **Existing artwork is re-keyed by a migration, not abandoned.** 283 MB of fetched art, and any
   hand-uploaded covers, are moved rather than re-downloaded. The mapping can only be rebuilt by
   recomputing the old hash for every distinct `(artist, album)` pair, because **nothing in the
   database records the hash** — a file's name is the only trace of what it belongs to.

## Alternatives Considered

- **Hash `album_artist ?? artist` instead of `artist`.** One line, and it fixes the 328 fragmented
  albums immediately — this was the first proposal made to Jeff. Rejected because it is still an
  attribute-derived key: the cover still vanishes when an album is renamed, which is the failure this
  ADR exists to prevent and which the new metadata editor makes more likely, not less.

- **Folder as album identity.** What most self-hosted players do, and immune to retagging.
  Rejected on the measurement: 315 albums here span multiple directories, so every multi-disc set
  would split into "Disc 1" and "Disc 2" with separate covers. Retained as the *fallback* for the
  801 tracks that have no album tag at all, where it is the only signal available.

- **MusicBrainz release id as identity.** The most durable key in principle — stable across retags
  *and* moves. Rejected because 93.3% of the library does not have one. Retained as the first step of
  the cascade, where it is authoritative when present.

- **Do nothing, and correct the editor's caption instead.** Honest, and nearly free. Rejected because
  the caption is not the defect: art is genuinely stored 6,221 ways for 3,900 albums, generated art is
  produced repeatedly for the same record, and the wrong-cover-on-a-compilation problem would remain
  for every client rather than just being described accurately.

- **A composite natural key on `(album_artist_id, normalized_title)` with no surrogate id.** Avoids a
  UUID and one join. Rejected for the same reason as the better hash: the key is the data, so
  correcting the data moves the row's identity. A surrogate id is precisely what lets the matching
  inputs change without the identity changing.

## Consequences

- **Positive:** artwork survives a retag, which makes the metadata editor's drop target trustworthy
  rather than provisional — the property [ADR-0051](ADR-0051-edited-metadata-outranks-file-tags.md)
  gave to tags, extended to covers.
- **Positive:** one dropped cover applies to a whole album including compilations, which is what the
  editor already claims.
- **Positive:** ~2,300 redundant artwork slots collapse; fetching, generation and the
  `regenerate-stale` sweep all stop duplicating work.
- **Positive:** album identity inherits artist merges, so the existing artist cleanup UI quietly
  improves album grouping too.
- **Positive:** `albumHash.ts` — a JavaScript reimplementation of a Python normaliser and of SHA-256,
  kept in sync by hand — is deleted rather than ported.
- **Tradeoff:** a seventh definition of "album" exists during the transition. This ADR adds the
  entity and re-keys artwork; the six `GROUP BY` sites keep their own definitions until the read
  cutover, so they still disagree with each other and now also with `albums`.
- **Tradeoff:** the artwork migration moves 283 MB with no database record to check itself against.
  It quarantines rather than deletes, and 284 new keys receive more than one old key, so a precedence
  rule decides which cover survives a merge.
- **Tradeoff:** generated art is seeded from the artwork key (`generative_art.py:725`), so re-keying
  changes what every procedurally generated cover looks like. `GENERATIVE_ART_VERSION` is bumped so
  the existing sweep regenerates them.
- **Follow-up:** the read cutover — `list_albums`, album detail, the alphabet bar, artist-detail album
  lists, library stats, the music map, playlist diversity — onto `albums`, which is what finally
  removes the `?source=artist` parameter.
- **Follow-up:** exposing the album id in `AlbumSummary`, which is also what would let an album whose
  name contains a slash be addressed at all.
- **Follow-up:** an album merge UI, the counterpart to `admin_artists.py`.
- **Follow-up:** smart playlist rules persist literal album strings, so renaming a canonical album
  silently breaks a saved rule. An `album_id` operand is its own change.
