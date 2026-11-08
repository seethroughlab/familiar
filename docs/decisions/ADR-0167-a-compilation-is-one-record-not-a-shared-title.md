# ADR-0167: A Compilation Is One Record, Not a Shared Title

Status: accepted

Date: 2026-11-08

Extends [ADR-0052](ADR-0052-albums-are-a-first-class-entity.md)

## Context

Many compilations in this library have no album-artist tag. Without one, each artist's tracks would
form their own album with their own cover. ADR-0052 measured the worst case at 49 covers for one
box set. `detect_compilation_albums` (`backend/app/services/scanner.py:848`) prevents that. It runs
after every library sync (`backend/app/services/tasks/library_sync.py:281`) and finds album titles
held by more than one artist among tracks with a blank album artist. It then writes "Various
Artists" into those tracks' `album_artist`.

**It groups by title across the whole library.** A title is not a record. Portishead's *Third* and
Soft Machine's *Third* are two artists sharing a title, so Portishead's tracks became "Various
Artists". *Greatest Hits* by The Cars and by Smashing Pumpkins went the same way, as did *Classics*
by Aphex Twin and Ratatat, and *Peel Session* by Boards of Canada and Clinic. The label then became
identity: the Portishead tracks' `canonical_album_artist_id` is the "Various Artists" artist. The
album key is that artist's id plus the title, so every falsely labelled *Third* shares one key.
**Portishead's 9 tracks and Soft Machine's 4 are one album today, with one cover.** *Greatest Hits*
fuses The Cars, Smashing Pumpkins and four strays in the same way. Some
tracks escaped the label, because they carry a MusicBrainz release id and resolved on their own.
Those tracks became a second album with a second artwork slot. That is most of the 35 split
folders [ADR-0166](ADR-0166-album-membership-is-corrected-through-proposed-changes.md) repairs, *TRST*
and *Third* among them.

Measured on the live library on 2026-11-08: 173 titles held by more than one artist carry "Various
Artists", 2,173 tracks in all. They split four ways, by folder and by whether two artists repeat a
disc and track number:

| Tracks live in | Track numbers repeat between artists | Titles | Tracks |
|---|---|---|---|
| one folder | no | 55 | 682 |
| one folder | yes | 2 | 11 |
| several folders | no | 92 | 1,050 |
| several folders | yes | 24 | 430 |

The "several folders, no repeats" row is the case that rules out the simplest fix. It holds 92
compilations stored one artist per folder, such as *Parts in the Post* across 17 artist folders and
the *Hohokum* soundtrack across 13. Their track numbers interleave into one sequence. A folder-only
rule would split every one of them.

The "repeats" rows are where the false compilations are: *Third*, *Greatest Hits*, *Finest Hour*,
*Singles*, *Purple Rain*, *Medúlla*, *TRST*. Each has two or more artists with a run of their own
starting at track 1. Those rows also hold some real compilations whose disc numbers are missing,
such as *The Wire 20 Years* (40 artists, one track each), so a repeat alone can't be the verdict.

A dry run of the rule below on the same tracks, computed off the server, found:
- Of the 2,258 tracks labelled "Various Artists", it would itself write 1,642. The detector never
  removes a label, so the other 616 are only a pool that point 4 draws its proposals from.
- It would newly label 31 blank tracks. Nearly all are a track of a compilation whose other
  tracks are already labelled, such as *Snow Robots vol 2*, *Nothing Changes* and *WARP Remixes, Vol. 3*. The exception is a title two artists share
  with two tracks each, such as *Peel Session* (see Consequences).
- It keeps every compilation stored across artist folders whole: *Parts in the Post* (19 of 19),
  *Hohokum* (5 of 5), *Yoshiesque* (15 of 15), *The Wire 20 Years* (40 of 40).

## Decision

1. **A shared title is a compilation only when the evidence says it is one record**, as follows:
   - Tracks in **one folder** under one title are a compilation when they hold more than one
     artist **and no artist holds more than half of them**. An album with a guest-credited track,
     such as Plaid's *Not for Threes* with one track credited to Björk, stays its artist's album.
     The old rule labelled those whenever the guest's track had a blank album artist.
   - Tracks across **several folders** are a compilation when no disc and track number repeats
     between different artists, and again no artist holds more than half. Unnumbered tracks can't
     repeat, so they don't count against it. The majority test is what keeps *Psyence Fiction*,
     with 12 UNKLE tracks and one under a variant spelling in another folder, from qualifying.
2. **When numbers repeat across folders, an artist with three or more tracks of their own under
   the title is their own album** and is left out. Whatever remains is judged by the same
   majority test.
   - *Third*: Portishead (10) and Soft Machine (4) are both left out, so nothing is labelled.
   - *Greatest Hits*: The Cars and Smashing Pumpkins are left out. The one-track strays from the
     other artists stay grouped together, as they are today.
   - *The Wire 20 Years*: no artist has three tracks, so it stays one compilation.
3. **The rule is a pure function from track rows to the set of tracks to label**, tested on the
   cases named here: *Third*, *Greatest Hits* and *TRST* are not compilations; *Parts in the
   Post*, *Hohokum* and *The Wire 20 Years* are. The detector still writes only into a blank
   `album_artist`, and still runs after every sync.
4. **Labels the old rule got wrong are offered back, not silently undone.** The detector wrote
   into the column with no record that it did. So a value it wrote can't be told apart from one a
   tag supplied, and reverting them unasked could undo a deliberate tag.
   - A pass finds tracks labelled "Various Artists" that the new rule would not label, and
     whose folder holds a single track artist.
   - Those tracks usually share one album with a different record, because the label also keyed
     their identity on the "Various Artists" artist. So the repair is an ADR-0166 **split**
     proposal, which moves each artist's tracks to their own album, rather than an `album_artist`
     edit, which would fix the text and leave the records fused. The reason is stated, for example:
     "'Third' was marked a compilation because Soft Machine also has a 'Third'."
   - The pass runs once, and again only by hand, from the endpoint that already starts the scan
     for proposals (`backend/app/api/routes/proposed_changes.py:212`).

## Alternatives Considered

- **Remove the detector and trust the files.** This is the simplest option, and it would never
  invent a compilation. Rejected: 147 titles and 1,732 tracks (the two "no repeats" rows) are real
  compilations that rely on it. Without it they would go back to one album and one cover per
  artist, the defect ADR-0052 measured at 49 covers for one box set.
- **Limit detection to one folder.** It's simple, and it is right for every case in the one-folder
  rows. Rejected: the 92 compilations stored one artist per folder would each split.
- **Use the MusicBrainz release id or a compilation tag as the evidence.** This would be
  authoritative where present. It isn't the rule because release ids are on about 7% of tracks
  (1,782 of 26,422 in ADR-0052), and the scanner doesn't read a compilation flag. It can be added
  as stronger evidence later without changing points 1–2.
- **Revert every "Various Artists" the new rule wouldn't write.** This is the fastest repair.
  Rejected for the reason in point 4: the column doesn't record who wrote a value, and a bulk revert
  would also undo tags the listener chose.

## Consequences

- **Positive:** the next album that shares a title with another artist's stays its artist's
  album, and stops becoming a new split album with a missing cover.
- **Positive:** the rule is a tested pure function rather than a SQL `HAVING` clause, so the cases
  that went wrong are pinned.
- **Tradeoff:** a record mostly by one artist is that artist's album, even when it is sold as a
  compilation. A soundtrack where the composer holds most tracks would not be labelled "Various
  Artists" by the detector. Existing labels stay, since the detector never removes one.
- **Tradeoff:** the threshold of three tracks is a judgement. Two artists with two tracks each under the same
  title would still be grouped, as *Peel Session* (Boards of Canada and Clinic) is. They are
  grouped today, too.
- **Tradeoff:** a compilation stored across folders with missing disc numbers and three or more
  tracks by one artist loses that artist to their own album. That is the price of not mislabelling
  *Third*.
- **Follow-up:** record where an `album_artist` value came from (the file, an edit, or the
  detector), so a future rule change can revert its own writes safely.
- **Follow-up:** read the compilation flag (`TCMP` / `cpil`) at scan time as evidence that
  outranks point 1.
