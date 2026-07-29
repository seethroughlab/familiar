# ADR-0009: Offline Downloads Are Background Transfers to a File Store

Status: proposed

Date: 2026-07-29

Extends [ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md)

## Context

[ADR-0001](ADR-0001-native-apple-clients-supersede-capacitor.md) rests on offline downloads more
than on anything else it cites. Its rejection of the cheapest alternative is unambiguous:
"Renovate the PWA instead. Rejected. It cannot deliver background downloads on iOS, which is the
strongest of the three reported symptoms." Eleven commits into `familiar-apple` the app browses,
plays, reports listening and adopts a queue left by another device — and downloads nothing. The
load-bearing claim of the entire programme is still unexercised.

**Three premises this ADR was drafted from turned out to be wrong, checked against the code rather
than assumed. They are recorded because each one made the work look larger than it is.**

1. **"Playback streams, so downloading is a new mechanism."** It is not.
   `NativeAudioEngine.load(url:trackId:)` (`Sources/FamiliarKit/NativeAudioEngine.swift:729`) issues
   a `URLSession.shared.downloadTask` (`:745`), moves the result into `NSTemporaryDirectory()`,
   opens it as an `AVAudioFile`, and deletes it when the next track loads (`ManagedTempFile`,
   `:406-412`). **Every play is already a whole-file download to disk.** There is no streaming
   playback to preserve, and a download is mechanically the file the engine already fetches, kept
   instead of discarded.

   That is forced rather than chosen: `AVAudioPlayerNode` takes an `AVAudioFile` or PCM buffers and
   has no remote-URL API, and `AVAudioFile(forReading:)` needs a local path. The whole reason the
   engine exists depends on it — the `AVAudioUnitEQ`/reverb/delay/`WaveshaperAudioUnit` chain, the
   FFT tap feeding the visualizer (`:1794`), sample-accurate seek via
   `scheduleSegment(file, startingFrame:)` (`:941`), and crossfade across two player nodes each
   scheduled with its own file (`:1339`), which is also why the *next* track is preloaded whole.
   The API that streams is `AVPlayer`, which supplies none of that graph; `git log -S"AVPlayer"`
   over every Swift file in both repositories returns nothing, so the trade was made implicitly at
   `cbb6b0a feat: add native iOS audio engine with AVAudioEngine, effects, and FFT visualizer`
   (2026-03-02) rather than weighed. Keeping the graph *and* streaming is possible —
   `AVAudioSourceNode` or scheduled PCM buffers fed by a progressive download through
   `AudioFileStream`/`AVAudioConverter` — but it means owning demux, decode and buffering for every
   codec in the library, and forfeiting sample-accurate seek. The cost of the status quo is that
   time-to-first-audio is the whole file: hidden by preload on auto-advance, exposed on first press
   and on a manual skip, negligible on a LAN and not negligible over Tailscale from outside it.

2. **"Playing from disk needs engine work."** `loadLocal(path:trackId:)` has existed since the
   Capacitor app (`:787`), and the auto-advance path already routes `file://` to it (`:1486`,
   `:1512-1515`). The half of offline playback that looks hardest is built.

3. **"Downloads need the profile header, so they cannot use a plain background session."**
   `GET /tracks/{id}/stream` is unauthenticated — it takes `db`, `track_id` and `request` and no
   `RequiredProfile` (`backend/app/api/routes/tracks/streaming.py:84-88`), which `FamiliarPlayer`
   already records as what "makes the engine's headerless download work unchanged"
   (`Sources/FamiliarKit/FamiliarPlayer.swift:91-93`). A background transfer needs no credential
   plumbing.

What is actually missing is narrower than it appeared: a transfer that survives app suspension, a
permanent place for the bytes, a record of what is there, and a decision at play time about which
URL to use.

**What the web client does today, and why it is not the model to port.**
`packages/frontend/src/services/offlineService.ts` (731 lines) and
`packages/frontend/src/stores/downloadStore.ts` (475) fetch a track as a `Blob` and then split: on
web the blob goes into IndexedDB (`offlineService.ts:315-319`); on Capacitor iOS it is
base64-encoded across the bridge into the filesystem (`:297-299`). The cost of that encoding is
legible in the code as memory choreography — `chunks.length = 0; // free constituent chunk Blobs
before base64 encoding` (`:274`), and a helper extracted specifically so "`blob` goes out of scope"
(`:146`). `edd96c5 fix: fail loudly instead of silently blob-storing on native iOS download` records
what the mechanism produced: with the Filesystem plugin unavailable the download landed silently in
IndexedDB, where `resolveTrackUrl` could not find it, so playback always fell back to the server. A
download nobody could play.

**The Apple client has no persistence to build on.** Nothing in `familiar-apple` stores state except
`UserDefaults` (`App/Shared/ServerConfiguration.swift`) and one on-disk file queue
(`Sources/FamiliarKit/ListeningEventQueue.swift:58`). There is no Core Data stack, no SQLite, no
schema. Whatever this ADR chooses is the client's first store, and later offline work inherits it.

Constraints that narrow the choice, all verified:

- The floor is **iOS 15 / macOS 13** (`Package.swift`; `IPHONEOS_DEPLOYMENT_TARGET = 15.0` and
  `MACOSX_DEPLOYMENT_TARGET = 13.0` in `Familiar.xcodeproj/project.pbxproj`). SwiftData requires
  iOS 17 and is not available.
- Testable logic must live in **`FamiliarKit`**: the test targets depend on `FamiliarKit` and
  `FamiliarAPI`, and `App/Shared` is not visible to `swift test`.
- [ADR-0006](ADR-0006-offline-ranking-is-precomputed-server-side.md) already decided that the client
  owns the offline set and the server keeps no record of it, and shipped
  `POST /api/v1/queue/offline-manifest` (`backend/app/api/routes/queue.py:653`, bounded by
  `MAX_OFFLINE_TRACKS = 10_000` at `:52`, `DEFAULT_NEIGHBOURS = 10` in
  `services/offline_manifest.py:39`). The `queue` tag is in the generated Swift surface
  (`Sources/FamiliarAPI/openapi-generator-config.yaml`), so the Apple client can call it today.
  Nothing does — offline ranking exists on the server for a client that cannot yet be offline.
- `TrackResponse` does **not** expose `file_size` (`backend/app/api/schemas/tracks.py:30-53`) even
  though `Track.file_size` exists (`backend/app/db/models/tracks.py:36`). A client cannot size a
  download before starting it, or show a storage estimate for an album.
- `needs_transcode` is **browser-shaped**: `needs_transcode_check()` returns true for codecs outside
  `BROWSER_SUPPORTED_CODECS`, and for FLAC or PCM above 24 bits
  (`backend/app/services/flac_remux.py:57-67`); `/stream` then serves a cached FLAC transcode. A
  native client downloading through `/stream` stores transcoded bytes for files AVFoundation would
  have decoded natively.

## Decision

The Apple client downloads with `URLSession` background transfers into a file store it owns, and
prefers that file at play time.

1. **Transfers are background transfers.** One
   `URLSessionConfiguration.background(withIdentifier:)` session for the app, delegate-driven,
   retaining `resumeData` on failure so an interrupted download continues rather than restarts. This
   is not an optimisation — it is the specific capability a WebView cannot have, and the reason
   ADR-0001 chose native over renovating the PWA. macOS does not suspend apps the same way, but it
   uses the same session so there is one code path rather than two.

2. **Audio is stored as ordinary files**, at `Application Support/Downloads/<track-id>.<ext>`, with
   the extension derived from the response `Content-Type` through the engine's existing
   `extensionForMIME` (`NativeAudioEngine.swift:1839`), and the directory marked
   `isExcludedFromBackupKey`. Not `Caches/`: the system may purge it, and a track deliberately
   downloaded before a flight must not be the thing that gets evicted. Not a blob in a database:
   `AVAudioFile` and `loadLocal` want a path, and storing audio in a database means copying it back
   out to play it — which is what the base64 bridge did.

3. **A `DownloadStore` in `FamiliarKit` records what exists**: track id, file name, byte size,
   state, and the metadata needed to list and play the track with no server reachable (title,
   artist, album, duration). It is persisted as a single `Codable` index written atomically, with
   writes coalesced during bulk downloads — not a database. At the endpoint's own ceiling of 10,000
   tracks the index is a low single-digit number of megabytes, it has no schema migration story to
   get wrong, and it is directly unit-testable in `FamiliarKit`, which the constraint above makes
   the deciding factor.

4. **The filesystem is the truth; the index is a cache of it.** On launch, reconcile: an index entry
   whose file is missing is dropped, a file with no index entry is deleted. ADR-0006 recorded this
   exact failure class in the web client — `offlineScoring.ts` read `db.cachedTracks` and could
   therefore pick a track whose audio was never downloaded. Here it is asserted by a test rather
   than intended.

5. **Play time asks the store first.** The app maps `TrackResponse` into `PlayableTrack` at the point
   of play; that mapping consults the store and substitutes a `file://` URL where one exists, falling
   back to `ServerConfiguration.streamURL(trackID:)`. One seam has to close with it:
   `FamiliarPlayer` calls `engine.load(url:)` (`FamiliarPlayer.swift:355`), and only the
   auto-advance path routes `file://` to `loadLocal` today, so `load(url:)` gains the same routing.

6. **What downloads is chosen explicitly, on the device.** A track, album or playlist is downloaded
   by an explicit action. v1 does **not** mirror the server's auto-download intent
   (`Playlist.auto_download`, `profile.settings["favorites_auto_download"]`), which the web client
   acts on via `hooks/useAutoDownload.ts` (62 lines). That is deferred on scope, not principle: it
   needs a background refresh path and a reconciliation policy for intent that changed while the
   device was away, and neither is worth designing before explicit downloads work end to end.

7. **The offline set is posted to the manifest endpoint whenever it changes**, and the response
   cached beside the index. This implements ADR-0006 decision points 2 and 3 on a second client
   rather than deciding anything new, and it is what makes downloaded tracks usable by radio and
   ambient offline instead of merely playable by hand.

8. **Downloads take `/tracks/{id}/stream` unchanged**, browser-shaped transcode included. Forking
   the download onto a different byte path than the one playback has proven, in the same change that
   introduces downloads at all, trades a real risk for saved disk space.

9. **Offline browse in v1 is the downloads list.** The index carries enough metadata to browse and
   play what is downloaded with no server. Caching the whole library — 23,000 tracks — for offline
   browse is a separate decision and is not made here.

10. **Nothing is evicted automatically.** Removal is an explicit act; the app shows what is used.
    An automatic budget that quietly deletes tracks reintroduces "my music vanished before the
    flight", which is the symptom this whole effort exists to remove.

## Alternatives Considered

- **Port `offlineService.ts`'s model — download to a store keyed by id, hand playback a URL derived
  from it.** Rejected. Its structure exists to work around IndexedDB being the only durable store a
  browser has. On Apple the file *is* the natural unit, the engine already consumes a path, and the
  base64 bridge that made the model painful is exactly what is being deleted.
- **A foreground `URLSession` download task, as the engine already uses for playback.** Rejected,
  and it is the tempting option because the code is already there. It dies when the app suspends —
  the precise gap ADR-0001 cites as the strongest argument for going native. Shipping it would leave
  the ADR's central claim still untested while looking done.
- **`AVAssetDownloadTask`.** Rejected. It is built for HLS assets and yields an opaque managed
  bundle; the server serves whole files with Range support, not HLS playlists, and the engine wants
  an `AVAudioFile`.
- **Core Data for the index.** Rejected. A managed object model inside a SwiftPM target — where all
  testable logic must live — is awkward to build and load, and buys migration machinery, faulting
  and relationship management for one flat table. **SwiftData** is unavailable at the iOS 15 floor.
- **Raw SQLite.** Rejected for v1 on the same size argument, and recorded as the thing to move to if
  the index outgrows an atomic rewrite. It is the right answer at a library-wide offline cache; it is
  not the right answer at one table of a few thousand rows.
- **Derive the offline set server-side from auto-download playlists and favourites.** Already
  rejected by ADR-0006 (decision point 3 and its alternatives): it is intent rather than state, and
  a server confidently wrong about what is playable offline is a harder failure to notice than one
  that asks. Not re-litigated here.
- **Download the original file via a new `original=true` parameter on `/stream`.** Deferred rather
  than rejected — it is a backend change, and see decision point 8. Recorded as a follow-up because
  the space saved is real for the AIFF and high-bit-depth cases.
- **An automatic storage budget with LRU eviction.** Rejected for v1. It is the correct long-term
  behaviour for a 23,000-track library on a 128 GB phone, but it must not be the first eviction
  policy shipped, because its failure mode is silent and lands at the worst moment.

## Consequences

- **Positive:** ADR-0001's strongest argument becomes testable. Either background downloads work end
  to end on a real device or they do not, and either answer arrives while the client is small enough
  to act on.
- **Positive:** The engine needs almost nothing. `loadLocal` exists, `file://` routing exists on one
  path and is a small addition on the other, and the download path is the one the engine already
  runs. The work is a store, a session and a resolver.
- **Positive:** ADR-0006's manifest gains its first native consumer, and offline radio and ambient
  become reachable on the Apple client for free once the offline set is posted.
- **Positive:** The client gets a persistence story chosen deliberately, at the smallest possible
  scale, before anything larger depends on it.
- **Tradeoff:** A `Codable` index rewritten atomically is a decision with a ceiling. It is chosen
  knowing SQLite is where it goes next; the trigger should be a library-wide offline cache, not a
  vague sense of scale.
- **Tradeoff:** Downloads store transcoded bytes for tracks whose codec only browsers object to. The
  files are larger than the library originals and are not byte-identical to them.
- **Tradeoff:** Two download surfaces now exist — the web app's and the Apple client's — with
  separate offline sets and no shared record. That is intended (ADR-0002 point 4: divergence is the
  outcome, not drift), but "downloaded" means different things on different devices, and the UI
  should not imply otherwise.
- **Follow-up:** Expose `file_size` on `TrackResponse` (a backend change under
  [ADR-0007](ADR-0007-clients-are-generated-from-openapi.md)) so a download can be sized before it
  starts and an album's cost shown before it is committed to.
- **Follow-up:** Decide whether `/stream` gains a way to serve original bytes, per decision point 8.
- **Follow-up:** Artwork offline. The engine fetches now-playing artwork by URL; a downloaded track
  played in airplane mode currently shows none. The web client caches artwork blobs; the Apple
  client needs an equivalent, and it is small enough to fold into the store rather than deserving an
  ADR.
- **Follow-up:** Auto-download intent (decision point 6), once explicit downloads are proven.
- **Follow-up:** An opportunistic cache of what was played. Because the engine already writes the
  complete file to `NSTemporaryDirectory()` and then deletes it, keeping it under a size policy is a
  small addition to this store rather than a second mechanism — and it would cut time-to-first-audio
  on a repeat play from a whole-file fetch to nothing. It is deliberately not decided here: bytes
  retained because they happened to be fetched are a different thing from a track the listener asked
  for, and mixing the two would make decision point 10's "nothing disappears" promise unclear about
  which is which.
- **Follow-up:** Full offline library browse (decision point 9), which is the decision that decides
  whether the index becomes SQLite.
