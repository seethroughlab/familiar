# ADR-0137: The Phone Keeps a Copy of Its Library

Status: accepted; point 5 superseded by [ADR-0150](ADR-0150-each-server-and-listener-gets-8-gb-on-a-device.md)

Date: 2026-09-29

Implementation:
- Accepted 2026-10-04. Client-only: every point is built in `familiar-apple`, and the server is
  untouched. Planned as five slices, in this order. The order differs from the numbering, and the
  budget deliberately lands before the default.
  1. **The away state (point 4)** and the reachability it depends on: "can this phone see its
     server", which is not `Connectivity.isOnline`. Point 3's triggers and point 4's dimming both
     need it. Offline favourite toggles join the event queue here.
  2. **The storage budget (point 5, now ADR-0150).** It comes before point 1 so that turning the
     default on can never fill a phone without a bound. ADR-0150 replaced "a share of free space"
     with 8 GB per server and profile, which needs storage split per pair first.
  3. **The pairing offer (point 1).**
  4. **Kept playlists and the sync that follows them (points 2 and 3).**
  5. **The Mac against a server on the same machine (point 6).** It depends on nothing above, so
     it can move earlier.
- **Slice 1 built 2026-10-04** in `familiar-apple`, not yet run on a device:
  - #210: reachability from the contract check, and the away state in the player and rows.
  - #211: "Needs <server>" wherever the server is needed.
  - #212: favourites kept on disk, with changes made away queued as absolute adds and removes.
    **There had been no favourites cache at all**, so a phone launched away from its server
    showed no favourites. Point 4 assumed browsing worked from cache everywhere.
- **Slice 2 built** as ADR-0150 (#213–#216).
- **Slices 3–5 built 2026-10-04**, not yet run on a device:
  - #217: point 1. The toggle is above the profile list, because choosing a profile saves at once.
  - #218: point 6. Same machine is decided by address, loopback or one of this Mac's own, which
    covers both ways a same-Mac server is paired without browsing. The play cache is off too.
  - #219: points 2 and 3. `KeptSet` and one `syncKeptTracks()` replace the favourites-only
    auto-download. **A sync that cannot read every rule releases nothing**, so a network blip is
    never why music leaves the phone. Un-favouriting a kept favourite now releases it, which it
    did not before.
- **Follow-up:** point 3's opportunistic background refresh is not built. It needs a
  `BGTaskScheduler` identifier and background modes in `familiar-apple`'s Info.plist. Foreground
  and the server's return cover the cases the point names.

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
- **Favourites auto-download**, a device-local setting per profile that defaults to off
  (`familiar-apple`'s `ServerConfiguration.favoritesAutoDownloadEnabled`,
  `FamiliarKit/FavoritesAutoDownload.swift`).
- **A one-time "Download" for an album or playlist** (`App/Shared/BrowseViews.swift`), which
  fetches what is there now and does not follow later additions.

What is missing is not a mechanism but a default: nothing treats the phone's copy as the normal
state of affairs.

**The first draft had the auto-download setting wrong.** It said the setting followed the profile's
server-side `favorites_auto_download`, and its third alternative rejected making it device-local.
That move had already happened on 2026-08-05: ADR-0029 point 4, `familiar` #99 and `familiar-apple`
#71. The server value survives only as a seed. `ServerConfiguration.seedFavoritesAutoDownload` copies
it across once per profile, and the endpoints at `backend/app/api/routes/favorites.py:141` and `:162`
are deprecated. Point 1 below is written against the device-local setting, and the rejected
alternative has been replaced with a real one. Checked against both repositories on 2026-10-04, before
acceptance. The rest of the list above held. Three things this ADR treats as new were confirmed
missing. `Connectivity` reports only whether the device has a network, never whether the server
answers. No favourite toggle is queued offline. And nothing on the Mac detects a server on the same
machine.

## Decision

1. **Pairing a phone to any server offers "Keep my favourites on this phone", on by
   default.** Accepting it turns on this device's auto-download for the paired profile
   (ADR-0029 point 4) and marks that profile's seed as done. Otherwise the first launch would copy
   the server's deprecated value, off by default, over the answer just given. The existing
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
- **Leave auto-download off by default and promote it in Settings instead.** Nothing would fill a
  phone without being asked, and the setting already exists (Settings → Downloads). Rejected: an
  off-by-default setting is found by people who already know they need it, and they find out when
  they are already away. Away from the server, the phone would show a catalogue of dimmed rows, which
  is point 4's honest state with nothing in it. Offering the choice at pairing, with the size spelled
  out, asks the question while the server is in reach to answer it.

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
