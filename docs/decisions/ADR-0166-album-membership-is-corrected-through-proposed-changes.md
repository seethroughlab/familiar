# ADR-0166: Album Membership Is Corrected Through Proposed Changes

Status: accepted

Date: 2026-11-08

Extends [ADR-0052](ADR-0052-albums-are-a-first-class-entity.md)

## Context

ADR-0052 made an album an entity with a surrogate id, and filed artwork under that id. Its
Consequences list an album merge UI as a follow-up, "the counterpart to `admin_artists.py`". That
was never built. The `merge_albums` change type was reserved in the `ProposedChange` model
(`backend/app/db/models/metadata.py:27`), but no code reads it. As written,
`ProposedChangesService.apply` would mark such a change applied and do nothing, because it acts
only on `change_type == "metadata"` (`backend/app/services/proposed_changes.py:308`).

The gap turned up while tracking down covers that should have shown. *TRST* by TR/ST is one folder,
`/music/TR_ST/TRST`. On 2026-11-08 it was two albums: nine tracks tagged with album artist "Various
Artists" and two with no album artist but carrying a MusicBrainz release id. Each half had its own
artwork slot, so only one half showed a cover. Measured on the live library the same day:

- **35 folders hold one album title split across 74 albums, 369 tracks in all.** The pattern is
  almost always the same: a stray "Various Artists" album artist on some tracks, or a blank one on
  tracks that also carry a release id. The blank-plus-release-id case resolves through step 1 of
  the cascade (`album_resolver.py:206`), and its siblings resolve through the alias.
- **Most of the stray "Various Artists" values were written by Familiar, not by a tagger.**
  `detect_compilation_albums` (`scanner.py:848`) runs after every library sync. It treats any
  album *title* shared by more than one artist, anywhere in the library, as a compilation. So
  Portishead's *Third* became "Various Artists" because Soft Machine also has a *Third*.
  [ADR-0167](ADR-0167-a-compilation-is-one-record-not-a-shared-title.md) fixes that cause. This ADR
  repairs what it has already split, so **0167 lands first**: merging while the detector still
  runs would leave the next shared title to split again.
- A further ~13 album titles are split because **the album exists twice, in two folders**.
  Examples: `/music/Breeders/Pod` and `/music/The Breeders/Pod`, and `/music/Trust/TRST` and
  `/music/TR_ST/TRST`, which are byte-identical in bitrate. Merging these would produce one album
  with every track listed twice. They are duplicate files, and only the listener can delete them.

**The obvious fix doesn't work, and the reason is deliberate.** Correcting the album artist through
Proposed Changes sets `track.album_artist` and records an override (`proposed_changes.py:327–344`),
but it never re-resolves `canonical_album_id`. The scanner explains why
(`backend/app/services/scanner.py:981–996`): identity resolves from the file's tags, and an edit in
Familiar corrects the display fields on top. An album renamed in Familiar must keep its cover,
which is the point of ADR-0052. So a tag fix regroups the album list, because `list_albums` still
groups by the album-artist text (`backend/app/api/routes/library_albums.py:133`). It leaves the
album's identity and its cover split. After that fix the album would look whole in the list and
still show a cover on only some tracks.

## Decision

1. **One change type moves tracks to the album they belong on: `move_to_album`.** It covers both
   repairs this library needs. A **merge** moves every track of one or more albums onto a kept
   album, as with *TRST*. A **split** moves one artist's tracks off an album that wrongly holds two
   records. Portishead's *Third* (9 tracks) and Soft Machine's *Third* (4) are today one album with
   one cover, because of the label ADR-0167 stops writing.
   - `target_type` is `"album"`.
   - `target_ids` lists **every track that moves**, so `_build_target_description` and the
     existing clients describe it unchanged.
   - `new_value` is `{"album_id", "album_artist"}`. A null `album_id` means "the album keyed by
     this artist and title", created if it doesn't exist.
   - `old_value` is everything needed to reverse the move (point 4).
   - The reserved `merge_albums` value is dropped from the model's comment, since nothing ever
     wrote it.
2. **Applying a move does this, in one transaction**, following the shape of `merge_artists`
   (`backend/app/api/routes/admin_artists.py:91`):
   - Lock the albums involved.
   - Repoint the tracks' `canonical_album_id` and `canonical_album_artist_id` to the target.
   - Write the chosen `album_artist` to every moved track as an ADR-0051 override, so the album list
     groups by the same text and agrees with the identity.
   - **An album left with no tracks is deleted**, after its tracks are repointed; the foreign key is
     `ON DELETE SET NULL`. If all of its tracks went to one album, that is a merge: its `AlbumAlias`
     rows move to the target, and the target takes its release id if it has none. Otherwise its
     aliases are deleted.
   - **Rescans keep the result**, without anything writing to a file. After a merge, the moved
     aliases resolve the files' own tags to the kept album. After a split, the detector's label was
     only ever in the database, so the files' tags already key on the track artist. The target
     album has that alias, registered if missing.
   - **Artwork:** if the target has no cover, copy one from the album the tracks came from. Covers
     filed under other ids stay on disk untouched; nothing deletes artwork.
3. **Two rules suggest moves, and both are limited to evidence in one folder or one artist.**
   - **Merge:** albums whose tracks share a containing directory, and whose titles agree under
     `normalize_for_matching`. The kept album is the one with the most tracks, with a tie going to
     the one with a release id. The proposed album artist is the most common non-blank one other
     than "Various Artists"; it falls back to "Various Artists" only when the folder holds more than
     one track artist.
   - **Split:** tracks labelled "Various Artists" that ADR-0167's rule would not label, grouped by
     track artist. They move to that artist's album for the title.
   - Both run beside the duplicate-artist scan in `app/services/auto_proposals.py`, and neither
     re-proposes a set of tracks already covered by a pending proposal.
   - **Two copies in two folders are never proposed for merging**, because merging them would hide
     a duplicate rather than resolve it.
4. **A move can be undone.** `old_value` records each track's previous album id, album artist id
   and album artist. For every album the move deleted, it also records the row (id, name, sort name,
   album artist id, release id, year) and its alias keys. Undo recreates deleted rows **with their
   original ids**, so their covers, still filed under those ids, come back with them. It then
   restores the aliases, repoints the tracks, and drops the album-artist override, as metadata undo
   does (ADR-0051 point 7). An album the move created is deleted again if it's left empty. A cover
   copied onto a target stays there, which is harmless.
5. **No client changes.** Both clients already show `reason` and the target description, and apply
   and undo through the generic endpoints. So the reason carries the explanation, for example:
   "11 tracks in /music/TR_ST/TRST are two albums: 9 have album artist 'Various Artists' and 2 have
   none. Merging gives them one album and one cover, under 'TR/ST'." `openapi.json` changes only if
   a schema does, and none is expected to.

## Alternatives Considered

- **Re-resolve `canonical_album_id` whenever `album_artist` or `album` is edited.** This would make
  the tag fixes alone sufficient, with no new change type. Rejected because it reverses ADR-0052
  point 4. Renaming an album in Familiar would move its tracks to a different album and leave the
  cover behind, which is the defect ADR-0052 was written to end. It also wouldn't catch a split
  caused by a release id, because the release-id step outranks the alias.
- **Make the resolver join the folder's existing album automatically**, when a track's title
  matches an album already holding a sibling in the same directory. This would heal splits at scan
  time, with nobody reviewing anything. Rejected because the result would depend on which file was
  scanned first. It would also silently regroup 369 tracks the listener never looked at. And it
  would be wrong in the 2.5% of directories that hold more than one album (ADR-0052's measurement),
  where a shared title such as "Greatest Hits" is not a shared album.
- **Only propose album-artist tag fixes.** This needs no new code: the existing metadata change
  type would carry them. Rejected because, as Context shows, the album list would be whole and the
  cover still split, so it only half works.
- **An admin merge endpoint like `merge_artists`, with no proposal.** This would allow merging any
  two albums by hand. Not rejected so much as deferred: it doesn't find the splits, and the
  Proposed Changes surface already exists on the Mac and the web with approve and undo. A manual
  move can reuse point 2's function later.

## Consequences

- **Positive:** the 35 split folders become merge proposals, and the albums the false label fused
  (*Third*, *Greatest Hits*, *Classics*, *Peel Session* and others) become split proposals.
  Approving one gives each record one identity, one cover and one row in the album list, and a
  rescan doesn't undo it.
- **Positive:** this builds ADR-0052's album merge follow-up, and goes further: the same operation
  takes tracks off an album, which nothing could do before.
- **Tradeoff:** a move writes an album-artist override onto every moved track. That is a choice
  that outranks the file, just like any accepted proposal. Undo is the way back.
- **Tradeoff:** proposals are limited to one folder. Duplicate copies across two folders stay split
  until the listener deletes one, which Familiar will never do for them.
- **Tradeoff:** if a file is moved to another folder after a move, its album follows its aliases,
  not the folder. That is correct, but invisible.
- **Tradeoff:** a compilation stored one artist per folder (*Parts in the Post* lives in 17 artist
  folders) can also be split. It isn't proposed here, because no single folder holds it. The
  manual merge below is how it would be repaired.
- **Follow-up:** a manual "move to album…" action, built on point 2's function.
- **Follow-up:** a duplicate-copies report for the two-folder case. This would be read-only and
  never a proposal.
