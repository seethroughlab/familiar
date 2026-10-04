# ADR-0149: An Artist Has a Gallery of Freely Licensed Photos

Status: accepted

Date: 2026-10-03

Implementation:
- **Accepted 2026-10-03**, as written.
- **Server half built 2026-10-03.**
  - `artist_images` (migration `20261003_artist_images`), plus `artists.image_chosen` and
    `artists.gallery_fetched_at`. `services/artist_gallery.py` gathers candidates — every Wikidata
    P18 image in the entity's order, the P373 category filtered to photographs (photo MIME types,
    600px short side, no logos, covers or vector files), fanart.tv thumbs and backgrounds only with
    a key — ranks them by point 7, caps at 24, and upserts by `(source, source_id)` keeping `hidden`.
  - Fetching: `schedule_gallery_fetch` from `GET /library/artists/{name}` when a gallery is missing
    or older than 90 days, and the deferrable `artist_gallery` job, 60 artists an hour, those with a
    MusicBrainz ID first. Both stand down while background work is paused, and when
    `FAMILIAR_ARTIST_GALLERY_FETCH` is off.
  - API (tag `library`): `images` and `images_state` on the artist detail; `POST
    /library/artists/{name}/images/{id}/hide`, `/unhide` and `/main`. Images stay external URLs:
    no new route, nothing added to `MEDIA_ROUTES`.
  - A fanart.tv card under Server › Providers, naming `FANARTTV_API_KEY`.
  - **Point 6 found a race in the existing resolver.** `_write_through_to_artist` read the artist,
    then wrote `image_url`; a background resolve that had loaded the row before the owner chose a
    main picture overwrote it — caught by the round-trip test, which once returned Björk's
    Wikipedia thumbnail over the picture it had just chosen. It is now one conditional `UPDATE …
    WHERE NOT image_chosen`; `test_a_resolve_already_holding_the_row_cannot_overwrite_a_chosen_picture`
    fails on the old code.
  - **The suite turns fetching off** (`settings.artist_gallery_fetch = False` in `conftest.py`):
    with it on, every artist page a test opened started a real fetch that reached the network and
    held locks a migration test's `DROP TABLE` deadlocked on.
- **Apps built 2026-10-03/04** (`familiar-apple` #205, then #206), in TestFlight builds 58–61.
  #205 drew a strip of 120pt thumbnails under the header; seen on a real Mac, it read as more
  furniture on a page that already opens with a grid of covers, and Jeff asked for **one hero
  slideshow at the top** instead. #206 replaced it: a full-width photo crossfading every 7 s with
  the artist's name, album count and duration over it, paused on hover, while the viewer is open
  and under Reduce Motion. The header drops its own name and picture when the hero is there. Point
  3 holds on the hero as well as the viewer: the photo on screen carries its own credit, a link to
  its page. Curation is the hero's and the viewer's context menu. A gallery still being fetched
  shows "Finding photos…" and asks again every 15 s, eight times, so the hero appears without
  reopening the page — the first build needed a reopen.
  - **A double fetch** (`familiar` #396, beta17): a page request that read the artist before a
    fetch committed scheduled a second one after it finished. The background task now re-reads
    staleness on its own row.
- **Coverage so far** (NAS, 2026-10-04, mid-sweep, Commons only — no fanart.tv key): 1,086 of
  3,538 artists fetched; **393 (36%) have at least one photo, 305 (28%) two or more, 183 ten or
  more**; 4,304 photos stored. Of the 60 artists with the most active tracks, 46 have a photo and 36
  three or more.
  Small electronic acts and new artists (no Wikidata item) have none, as the Tradeoff below
  predicted. The wrong-person rate is not measured yet: nothing has been hidden, which says no one
  has looked closely, not that there are none. Replace these figures after the sweep finishes —
  at 60 an hour, about two days from these.

Extends [ADR-0138](ADR-0138-a-desktop-server-yields-to-its-owner.md) (background work yields) and
[ADR-0126](ADR-0126-the-admin-ui-is-organized-around-operator-workflows.md) (a provider is one card)

## Context

The artist view shows one picture per artist, and that is all the data model can hold. Read on
2026-10-03:

- **One external URL per artist.** `Artist.image_url` (`backend/app/db/models/artists.py:48`) and
  the name-keyed `ExternalArtistImageCache` hold a single URL each. No artist image is stored on
  disk, and no source, size, author or licence is recorded.
- **The resolver stops at its first hit** (`backend/app/services/artist_image.py:585-645`):
  Wikipedia's page thumbnail, then MusicBrainz → its Wikipedia link, then Wikidata's P18 claim —
  **only `p18[0]`** — then Spotify's oEmbed thumbnail. Each is about 320px. Last.fm's image is
  promoted into the same column on the detail route.
- **The apps draw it at 72pt.** The Mac and iPhone artist header (`familiar-apple`
  `App/Shared/BrowseViews.swift`, `ArtworkThumbnail`) shows that one image beside the name; the grid
  shows it as a circle. Nothing in either repository models more than one image per entity, and the
  app has no gallery or full-size viewer.
- **Nothing records attribution**, although the Wikidata/Commons path already returns freely
  licensed photos (typically CC BY or CC BY-SA), whose licences require the author to be credited.

The owner asked for more pictures of an artist. Wikimedia Commons has many for most artists with a
Wikidata item, all under licences that allow reuse with credit, and needs no key. fanart.tv has
higher-quality portraits and wide backgrounds keyed by MusicBrainz ID, but needs an API key and its
images are fan-uploaded, with looser terms.

## Decision

1. **An artist has a gallery: an `artist_images` table**, many rows per artist, each recording its
   source, the source's own id, kind (portrait, photo, background), a large URL and a thumbnail URL,
   size, author, licence, licence URL, source page, rank, and whether it is hidden.
   `Artist.image_url` stays the single main picture that the grid, the list and the offline library
   cache read; the gallery does not replace it.

2. **Two sources, no others.**
   - **Wikimedia Commons, always.** Reached through the artist's Wikidata item (the QID from
     MusicBrainz's `wikidata` relation, using the stored `Artist.musicbrainz_id` when there is one):
     every P18 image, not only the first, and the photographs in the P373 Commons category.
   - **fanart.tv, only when an API key is set**, keyed by MusicBrainz ID: artist thumbnails and
     backgrounds. Its key is a provider card in Server › Providers.

3. **Attribution is shipped, not only stored.** Every Commons image keeps its author, licence and
   source page, and the apps show them with the photo: "Photo: {author} · {licence}", linking to the
   source page. fanart.tv images are credited to fanart.tv. ADR-0109's rule applies: an attribution
   requirement that lives only in a repository is not being met.

4. **Images stay external URLs**, loaded by the apps the way the artist image is today
   (`AsyncImage`, ADR-0111's deliberate exception for artist images). The server copies nothing,
   adds no route, and adds nothing to the token-exempt `MEDIA_ROUTES`. Offline photos are a
   follow-up, alongside ADR-0009's and ADR-0011's artwork gap.

5. **Fetching is background work, never on the request path.** Opening an artist schedules a fetch
   when its gallery is missing or stale; a slow sweep covers the rest of the library, refetching
   after 90 days. Both are deferrable jobs under ADR-0138, so a Mac on battery does not fetch. The
   detail response says whether photos are `ready`, being fetched, or there are `none`.

6. **The owner curates.** A photo can be hidden, and a hidden photo stays hidden across refetches
   (it is matched by source and source id). A photo can be made the artist's main picture, which
   writes `Artist.image_url` and marks it chosen, so the resolver no longer replaces it.

7. **Ranking:** the chosen main photo; Wikidata's P18 images; fanart.tv thumbnails; Commons category
   photographs; fanart.tv backgrounds. Category files are filtered to raster photographs at least
   600px on the short side, excluding logos, album covers and vector images. At most 24 are kept per
   artist.

## Alternatives Considered

- **Keep one image and fetch it larger.** Wikipedia's `originalimage` and Commons widths would make
  the existing picture sharper with almost no new code. Rejected as the answer: the request is for
  more pictures, not a bigger one. Its by-product — larger URLs — is taken anyway, since each
  gallery row carries a large URL.
- **Discogs and TheAudioDB as well.** More coverage for obscure artists. Rejected: two more keys,
  two more sets of terms and rate limits, and Discogs' terms restrict how its images are shown.
  Commons plus an optional fanart.tv covers the request; another source is a later ADR if coverage
  measured after the sweep says it is needed.
- **Copy every image onto the server.** It would make photos work offline and keep viewers' address
  from Wikimedia. Rejected for now: at 24 images for each of a few thousand artists the disk cost is
  real, ADR-0111 exists because transfers already compete, and an image route would join the
  token-exempt media routes ADR-0045 already records as a leak. Kept as the follow-up in point 4.
- **Search for images by name.** The widest net. Rejected: it returns the wrong person often, and
  carries no licence a page could honour.
- **Curation in the web admin only.** The admin is where the server is managed (ADR-0050). Rejected
  for this: deciding that a photo shows the wrong person happens while looking at the artist, which
  is in the player.

## Consequences

- **Positive:** most artists with a Wikidata item gain several freely licensed photos, credited as
  their licences require.
- **Positive:** the background path finally uses the stored MusicBrainz ID instead of searching
  again (`artist_image.py`'s background resolver passes `None` today).
- **Tradeoff:** viewing photos sends requests from the listener's device to Wikimedia or fanart.tv,
  as viewing the artist image already does.
- **Tradeoff:** coverage is uneven: good for artists with a Wikidata item and a Commons category,
  thin for small artists, whom fanart.tv also rarely has.
- **Follow-up:** after the first full sweep on the NAS, record coverage here — how many artists have
  more than one photo, and from which source — and how often the wrong person appears.
- **Follow-up:** offline photos and server-side caching (point 4).
