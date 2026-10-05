# ADR-0150: Each Server and Listener Gets 8 GB on a Device

Status: accepted

Date: 2026-10-04

Implementation:
- Accepted 2026-10-04. Built in `familiar-apple` in three parts, in this order: the per-pair
  storage partition (points 1, 3 and 6), the budget (point 2), then the warning and the storage
  screen (points 4 and 5).
- **Built 2026-10-04, all six points, as a stack in `familiar-apple`.** None of it had been run on
  a device when this was written.
  - #213: points 1 and 6. `StorageSpaces` hands out one `DownloadStore` per pair. A download
    request is stamped with its pair, which travels in the task description, so a transfer that
    finishes after a switch of server still lands with whoever asked. The shared folders are
    renamed into the pair in use, and never merged into a pair folder that already exists.
  - #214: point 3. The `Kept` directory and `DownloadRequest.residency`. Downloading a kept track
    moves it into `Downloads`.
  - #215: point 2. `StorageBudget`. The play cache's bound is 8 GB on the Mac too. **Auto-download
    queues only what the room left by kept tracks can hold**, which this ADR did not spell out:
    without it, the budget releases a favourite and the next launch fetches it straight back.
  - #216: points 4 and 5. `ServerConfiguration.storageNotice`, and "Storage on this device" in
    Settings → Downloads.
  - #221: the rest of point 5. Forgetting a server offers to remove what it kept, with Keep as the
    default, since a server forgotten by mistake should not cost its music.
- **#213–#216 merged 2026-10-05.** Point 6's move was then run on the owner's phone, a real
  install paired to the NAS: the downloads were all still listed afterwards and played in airplane
  mode, so the shared folders were renamed into the pair's and the player found its files there.

Supersedes point 5 of [ADR-0137](ADR-0137-the-phone-keeps-a-copy-of-its-library.md).
Extends [ADR-0010](ADR-0010-played-bytes-are-cached-downloads-are-pinned.md).

## Context

ADR-0137 point 5 gave kept tracks a budget "defaulting to a share of free space the owner can
change". The owner has since set the rule directly: **8 GB per server and profile, and say so when
a device starts holding more than one.**

Checked against `familiar-apple` on 2026-10-04, these facts shape the change:

- **Storage is global today.** `DownloadStore` keeps one directory, `Application
  Support/Familiar/Downloads` (`FamiliarKit/DownloadStore.swift`). `PlayCacheStore` keeps another,
  `Application Support/Familiar/Cache` (`FamiliarKit/PlayCacheStore.swift`). Every server and profile
  this device has used shares both. Track ids are per server, so a second server's files sit
  in the same folders as the first's, and nothing can free one server's share without the other's.
- **The play cache already has a budget**, from ADR-0010's measurement: 16 GB on the Mac and 8 GB on
  the phone (`PlayCacheStore.defaultBudgetBytes`). That budget is per device, not per server.
- **A device holds up to five server/profile pairs.** `RecentServers.limit` is 5, and
  each entry is one server with one profile. Five pairs at 8 GB each is 40 GB.
- **A download does not record why it was made.** `DownloadedTrack` carries an id, a file name,
  a size, tags and a completion time. So the favourites already fetched by auto-download
  (`FavoritesAutoDownload`, ADR-0029 point 4) cannot be told apart from tracks the listener
  downloaded by hand. ADR-0137 point 5 distinguishes the two ("auto-kept" against "downloaded
  explicitly"), and nothing on disk does.

## Decision

1. **Each server-and-profile pair on a device has its own storage.** Downloads, kept tracks and the
   play cache live under one folder per pair, keyed by the server's `server_id` (ADR-0134 point 4)
   or, for a server reached by typed address, its host and port, and then by profile id. Switching
   pair switches folder. A track downloaded for one listener is not visible to another.

2. **The budget is 8 GB per pair, on the phone and the Mac alike.** It covers two classes of file:
   - **kept** tracks, fetched because a rule said so: favourites auto-download, and kept
     playlists (ADR-0137 point 2);
   - **cached** tracks, kept because they were played (ADR-0010).

   When the two together would pass 8 GB, cached tracks are released first, least recently played
   first, then kept tracks in the same order. **Downloaded** tracks, the ones the listener asked
   for, are outside the budget and are never released automatically. That is ADR-0009 point 10's
   promise, unchanged.

3. **Kept is a third class with its own directory**, beside ADR-0010's pinned `Downloads` and cached
   `Cache`. ADR-0010 point 2 made a file's class its directory so reconciliation can repair a
   mislabel, and a rule-fetched file is a different class from a chosen one. Downloading a kept
   track explicitly promotes it into `Downloads` with a rename, as ADR-0010 point 6 does for a
   cached one.

4. **The device says so when it starts holding a second pair.** Connecting this device to a pair
   it has not held before, by pairing, by setup or from the recent list, shows the cost before
   anything is saved: "Each server and listener on this iPhone keeps up to 8 GB. With 3, Familiar
   may use up to 24 GB." The count is the pairs on the recent list plus the new one. It is shown
   once per new pair, never when switching between pairs the device already holds, and never for
   the first one.

5. **Storage on the device is shown per pair**, in Settings → Downloads: what each pair holds,
   split into downloaded, kept and cached, with a way to remove one pair's files. Forgetting a
   pair on the recent list offers to remove its files too, since nothing else can reach them.

6. **What is on disk at upgrade belongs to the pair in use then.** The global `Downloads` and
   `Cache` move into that pair's folder. Files from other servers cannot be attributed, because a
   track id says nothing about its server, and reconciliation against that pair's catalogue later
   releases the cached ones. Existing downloads all stay **downloaded**, auto-downloaded favourites
   included, because nothing records which they were. A listener who wants them counted against
   the budget can remove and re-keep them.

## Alternatives Considered

- **A share of free space, as ADR-0137 point 5 first said.** It adapts to the device without a
  number anyone has to pick. Rejected by the owner: the share moves as the phone fills with other
  things, so nobody can predict what Familiar will take, and it hides the cost of a second server
  inside a number that was already changing.
- **One budget for the device, shared by every pair.** No partitioning, and the total can never
  pass 8 GB. Rejected: the pair in use would evict the others' files every time it played, so
  switching back to a server would find its favourites gone. It also leaves the global folders,
  where removing one server's files is impossible.
- **Separate budgets for kept and cached tracks**, the play cache keeping ADR-0010's figure. Each
  class would get its own measured size. Rejected by the owner in favour of one number per pair a
  listener can hold in their head. That would mean up to 16 GB per pair, twice what anyone was
  told.
- **Keep the Mac at 16 GB**, ADR-0010's measured figure. It holds a third of plays against roughly
  a quarter at 8 GB. Rejected for one rule on every device. ADR-0137 point 6 already removes the
  Mac's largest case, a server on the same machine, where the Mac downloads nothing.
- **Count explicit downloads against the budget too.** One number would bound everything. Rejected:
  a full budget would then have to refuse a download or release one the listener chose. Both break
  ADR-0009 point 10, which promises that nothing asked for is removed.

## Consequences

- **Positive:** what Familiar can take is a number a listener can work out before agreeing to it,
  and the cost of every further server or listener is stated at the moment it is incurred.
- **Positive:** a server's files can be removed without touching another's, and forgetting a
  server can free its space.
- **Tradeoff:** on the Mac, the play cache shrinks from 16 GB to at most 8 GB, shared with kept
  tracks. ADR-0010's table puts 8 GB of cache alone at a 23.6% hit rate against 33.3% at 16 GB.
  Shared with kept tracks it will be lower. The cost falls on a Mac playing from a NAS.
- **Tradeoff:** two listeners on one device who both download a track hold it twice.
- **Tradeoff:** favourites auto-downloaded before this ships stay outside the budget (point 6)
  until removed and re-kept.
- **Follow-up:** the storage partition (points 1, 3 and 6) is the prerequisite for everything else
  here and for ADR-0137's slices 3 and 4. It lands first, then the budget, then the alert and the
  storage screen.
