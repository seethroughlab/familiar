# ADR-0149: An Artist Has a Gallery of Freely Licensed Photos

Status: proposed

Date: 2026-10-03

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
