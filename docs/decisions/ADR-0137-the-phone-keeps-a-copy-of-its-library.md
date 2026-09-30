# ADR-0137: The Phone Keeps a Copy of Its Library

Status: proposed

Date: 2026-09-29

Extends [ADR-0131](ADR-0131-the-server-is-its-own-app.md),
[ADR-0009](ADR-0009-offline-downloads-are-background-transfers.md),
[ADR-0011](ADR-0011-the-library-is-cached-whole-and-refreshed-by-delta.md),
[ADR-0118](ADR-0118-a-phone-downloads-lossless-tracks-as-aac.md)

## Context

The phone was designed against a NAS, as a streaming client that can also download. ADR-0131 adds a
second kind of server, Familiar Server on its owner's Mac, and a laptop is closed in a bag, asleep,
or on another network for much of any day. A NAS is out of reach too, as soon as the phone leaves
home without Tailscale. ADR-0134 point 8 leaves off-network access to Tailscale for
those who want it. For everyone else, **whether Familiar works away from home depends on what is
already on the phone.**

Most of the pieces already exist, built one at a time for the NAS:

- **Background transfers** that survive suspension (ADR-0009), with a Live Activity per batch
  (ADR-0121).
- **Lossless sources downloaded as AAC**, from a device-local preference that defaults to AAC on
  the phone (ADR-0118).
- **The whole library catalogue cached and refreshed by delta** (ADR-0011), so browsing does not
  need the server.
- **Listening events queued offline**, each carrying its own timestamp
  (`FamiliarKit/ListeningEventQueue.swift`).
- **Favourites auto-download**, following the profile's server-side `favorites_auto_download`,
  which defaults to off (`backend/app/api/routes/favorites.py:157`,
  `FamiliarKit/FavoritesAutoDownload.swift`).
- **A one-time "Download" for an album or playlist** (`App/Shared/BrowseViews.swift`), which
  fetches what is there now and does not follow later additions.

What is missing is not a mechanism but a default: nothing treats the phone's copy as the normal
state of affairs.

## Decision

1. **Pairing a phone to any server offers "Keep my favourites on this phone", on by
   default.** Accepting it sets the profile's `favorites_auto_download`. The existing
   `FavoritesAutoDownload` then fetches newest first, as AAC per ADR-0118. Nothing new is invented
   for the default case.

2. **A playlist can be kept, not only downloaded.** "Keep on this phone" makes a playlist's
   downloads follow its membership: additions are fetched, and removals are released unless the
   track is kept by something else (favourites or another kept playlist). This is a device-local
   list (ADR-0029: the server stores no listener preferences). The one-time "Download" stays.

3. **Syncing happens whenever the phone can see its server.** That means on foreground, when
   Bonjour reports the paired `server_id` (ADR-0134 point 4), and on an opportunistic background
   refresh. Each sync pulls:
   - the catalogue delta (ADR-0011)
   - the drained event queue
   - whatever the kept sets now require

   Transfers are ADR-0009's background session, so a sync started at home finishes in the
   phone's pocket.

4. **Away from the server, the phone is in a defined state, not an error.** Browse uses the cached
   catalogue. Held tracks play. Tracks not held are shown dimmed and are not offered to play.
   Writes the phone can make safely offline are queued: listening events already are, and
   favourite toggles join them. Everything else (radio, search that needs embeddings, management)
   says it needs the server, by the server's name ("Needs Studio MacBook"), rather than failing a
   request.

5. **Kept tracks have a storage budget.** It is device-local, defaulting to a share of free space
   the owner can change. When auto-kept tracks would exceed it, the least recently played are
   released first. Tracks the owner downloaded or kept explicitly are never released
   automatically.

6. **The Mac player does not download from a server on the same machine.** Same machine means
   the paired address is a loopback address, or the paired `server_id` matches the one advertised
   by a Familiar Server on this Mac (ADR-0134 point 4). Then download controls and auto-download are
   hidden, because every byte is already on the disk. Against any other server, a NAS included,
   the Mac behaves as today. This is ADR-0131 point 3's rule in practice: the player notices the
   case, and nothing fails when it is absent.

7. **Nothing wakes a sleeping server for the phone.** Sync is opportunistic on the phone's side.
   ADR-0138 forbids Familiar Server from holding its Mac awake for a client.

## Alternatives Considered

- **Keep the phone a streaming client and make the server reachable from anywhere** (a relay, or
  Tailscale set up by the app). The phone would have the whole library, not a subset. Rejected as
  the default: a sleeping laptop is unreachable by any network design, and a relay would also be needed for the
  NAS case. A relay also makes
  Familiar operate a service (ADR-0038 point 7's step), and managing Tailscale for the owner makes
  another company's product part of setup. ADR-0096 still documents Tailscale for those who want
  it.
- **Mirror the whole library onto the phone.** Nothing is ever missing. Rejected: a 26k-track
  library is hundreds of GB even as AAC, well beyond any phone. The kept sets (point 2) with a
  budget (point 5) are the same idea at a size a phone can hold.
- **Make auto-download a device-local preference instead of the profile's setting.** It would fix
  the odd case where the web app, the Mac and the phone all act on one flag. Rejected here as a
  separate problem: `FavoritesAutoDownload.swift` records why it follows the profile deliberately,
  and point 6 removes the case (the local Mac) where following it did harm.

## Consequences

- **Positive:** a coworker's phone plays their favourites on a train with their laptop asleep at
  home, or their NAS out of reach. That is the ordinary case under ADR-0131, and it now works by
  default.
- **Positive:** almost all of it is existing machinery given a default. The new parts are kept
  playlists, the budget, and the defined away state.
- **Tradeoff:** by default a phone fills with music. A 1,700-favourite collection is roughly 13 GB as 256 kbps AAC
  (four-minute tracks at 7.7 MB each). The budget bounds it, and the pairing screen says what "on" means before it is
  accepted.
- **Tradeoff:** "dimmed, needs your server" is a new, visible way for the app to say no. It is the
  honest version of today's failed request.
- **Follow-up:** offline radio from ADR-0006's precomputed rankings, restricted to held tracks,
  would make "away" feel less like a subset.
