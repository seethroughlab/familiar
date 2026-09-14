# ADR-0118: A Phone Downloads Lossless Tracks as AAC

Status: proposed

Date: 2026-09-14

Implementation:
- **Written before the code**, in the order ADR-0111 and ADR-0112 established, and the server half
  built the same day on this branch: `?format=aac` on `/tracks/{id}/stream`
  (`routes/tracks/streaming.py`), `TranscodeTarget` with `FLAC` and `AAC` in `services/flac_remux.py`,
  `is_lossless_source` beside the quality score it shares a set with (`services/quality.py`), and
  `EncoderLimiter` next to the file-response limiter in `api/concurrency.py`, sized from
  `TRANSCODE_CONCURRENCY`. Fifteen tests in `tests/test_stream_format_aac.py`, which drive the real
  endpoint with files ffmpeg made; the three lossy pass-through cases were run against the route
  with the lossless check removed and all three failed, so they guard the thing they claim to.
  Additive to the contract — the parameter is optional — so `contract.lock.json` was re-locked at
  v1 rather than bumped (ADR-0113 point 10). **Not yet deployed.** The client half is a
  device-local preference and one query parameter in `familiar-apple`'s `DownloadManager`; the
  plan across both repos is `familiar-apple/PLAN-lossy-downloads.md`.
- **One thing the code decided that the first draft of this record did not**: lossless is judged by
  *codec* first and suffix second. An ALAC file is `.m4a` — the same suffix as AAC — so a suffix
  rule would have handed a 30 MB ALAC back untouched with a straight face. `Track.codec` is what
  ffprobe said; `quality.py`'s own score still goes by suffix and now shares the set.
- **One measurement, taken on the NAS before writing** (`familiar-api` container, eight cores, load
  1.1, ffmpeg's built-in `aac` encoder — the image has no `libfdk_aac`):

  | | |
  | --- | --- |
  | source | `Squarepusher/Damogen Furies/01 - Stor Eiglass.flac`, 16/44.1, 4:32, **34.6 MB** |
  | `-c:a aac -b:a 256k` | **12.4 s**, one core, ~22× realtime |
  | output | ~8.7 MB (256 kbps × 272 s), a quarter of the source |

  That one number decides most of the Consequences: a first sync of ~1,700 favourites is on the
  order of six core-hours, once, and then cached.

## Context

**A phone download is the library file, byte for byte.** `familiar-apple` fetches
`GET /api/v1/tracks/{id}/stream` for a download exactly as it does for playback — the only
difference is the `X-Familiar-Intent: sync` header ADR-0112 point 3 added so the server could
tell the two apart for admission. `stream_track` serves the file on disk; the one transformation it
performs is a lossless one, remuxing AIFF and browser-unsupported codecs to FLAC through
`_get_or_transcode` (`streaming.py:121-128`). Nothing anywhere produces a smaller file than the
one in the library.

That was the right default for the library the app was written against and is the wrong one for
the library it has. Purchases from Bandcamp arrive as FLAC — 30 to 40 MB a track at CD resolution,
more for 24-bit — and they are a growing share of what gets favourited, because a purchase is a
strong signal of wanting to hear something again. The phone is where favourites go
(`FavoritesAutoDownload`), so the phone is where every one of those files lands in full.

Two incidents have already been paid for by that. On 2026-08-02 a bulk download of 1,720
favourites exhausted the database pool; on 2026-09-07 a sync of 1,589 took the disk and the
thread pool, with `/stream` requests completing in 180 to 424 seconds and **30.5 GB of partial
files on the phone against 385 filed tracks** (ADR-0111, ADR-0112). Both were fixed at admission,
correctly, and the fixes stand. But the size of what was being admitted was never questioned, and
it is the multiplier on everything: how long a worker is held per file, how many seeks the
spindle makes per track, how many gigabytes a phone has to find, and how long a sync over
Tailscale takes to finish.

**Nobody is listening to 16-bit FLAC on a phone in a way that distinguishes it from 256 kbps
AAC.** This is not a claim about ears in general; it is a claim about the listening a phone does —
earbuds, a car, a kitchen speaker over Bluetooth, which itself re-encodes to AAC or SBC on the way
out. The lossless file's value is archival, and the archive is the NAS. Every comparable client
has drawn this line the same way: Plexamp, Apple Music, Symfonium and Navidrome's mobile apps all
download at a lossy bitrate by default and pass lossy sources through untouched.

Two things the codebase already has make this small. The server already classifies every track
as lossless or lossy (`services/quality.py:95-117`: flac/alac/wav/aiff on one side, mp3/m4a/aac/
ogg/opus on the other) — the rule "never re-encode a lossy file" is a lookup, not new judgment.
And the server already has a transcode-and-cache path with per-track locking and mtime staleness
(`_get_or_transcode`, `data/transcode_cache`), built for the AIFF case; the AAC case is that path
with a different codec and a different suffix.

On the client side the pieces are also in place, which was checked before writing: `AudioFileExtension`
maps `audio/mp4` to `.m4a`, and the server sends no `Content-Disposition`, so the MIME type is what
names the file on disk; `DownloadIntegrity.looksLikeAudio` recognises `ftyp` at offset 4, so an
AAC body passes the check that keeps error envelopes out of the offline set.

## Decision

Downloads on the phone are AAC when the source is lossless, and untouched when it is not. Playback
is unchanged.

1. **The stream endpoint takes `?format=aac`.** `GET /tracks/{id}/stream?format=aac` serves the
   track as AAC in an MP4 container, `audio/mp4`, encoded once and cached. Without the parameter the
   endpoint does exactly what it does today, so no existing client changes behaviour by upgrading
   the server. The only accepted value is `aac`; an unknown value is a 422 rather than a fallback,
   because a client that asked for something the server does not know should find out.

   A query parameter rather than a header, and the reasoning is the inverse of ADR-0112's. The
   intent header was made a header so the URL stayed *identical* to playback: the same bytes, one
   cache key. Here the bytes differ, so the URL must too — `URLCache`, `nsurlsessiond`'s resume
   data and anything between the app and the server key on it.

2. **Only a lossless source is encoded.** The decision is `quality.py`'s lossless set — flac, alac,
   wav, aiff, aif by suffix, and `alac`, `flac`, `pcm_*` and friends by codec, the codec winning
   because `.m4a` holds both ALAC and AAC — and nothing else. A lossy source served with `?format=aac` is served as it is,
   with its own MIME type: an MP3 stays an MP3. Re-encoding lossy to lossy is a generation loss for
   no saving, and the parameter means "no larger than AAC", not "AAC". The client must therefore
   name the file from the response, not from the request, which is what `AudioFileExtension`
   already does.

3. **256 kbps, ffmpeg's native `aac` encoder, `+faststart`.** 256 rather than 192 because the cost
   of the extra 64 kbps is 2 MB a track and the cost of a transparent-or-not argument is the
   feature's credibility; 256 rather than 320 because above 256 AAC's returns are well documented
   as nil. The native encoder because it is what the image has and it is adequate at this rate;
   `libfdk_aac` would be better and is a one-line change if the image ever gains it, and the
   cache key includes the encoder so a change re-encodes. `+faststart` puts the `moov` atom first,
   which `AVAudioFile` needs to open the file without reading to the end and which range requests
   need to seek.

   Not Opus, although it is the better codec per bit: iOS decodes Opus only in a CAF container,
   and an `.opus`/Ogg file that plays online and fails offline is the exact failure `AudioFileExtension`'s
   docstring names as the worst this feature can have.

4. **The encode is cached to disk, per track, once — `data/transcode_cache/{id}.aac.m4a`.** The
   AIFF path's structure is reused: the per-track `asyncio.Lock` so two devices asking for the
   same track produce one encode, the mtime check so a retagged or replaced file re-encodes, the
   empty-file check for a crash mid-write, the temp-then-rename so a reader never sees a partial.
   Serving is `stream_file` on the cached file, so `Content-Length`, `Range` and `Cache-Control`
   are what they are for every other file — a cached encode is a file like any other.

5. **The encode runs under its own bound, separate from the file-response ceiling.** ADR-0112 gives
   sync a share of a twelve-slot budget on the assumption that a slot is held for a network
   transfer. An encode holds a *core* for twelve seconds before the transfer begins, which is a
   different resource — the incident this ADR is downstream of was the lesson that a ceiling on
   one resource moves the queue to the next. So: a semaphore of **four** concurrent encodes,
   acquired before ffmpeg starts and released when it exits, independent of the file-response
   slot the request also holds. Four of eight cores leaves the API, Postgres and the analysis
   workers the rest; a fifth request waits on the semaphore rather than being refused, because a
   wait of a few encodes is seconds and the client's `Retry-After` handling is for minutes.

   The cost is that a sync request can now hold a file-response slot while it waits for a core.
   That is accepted here and named in Consequences, because the alternative — refusing with
   `Retry-After` — turns a first sync into a wall of 503s, and after the first sync the cache
   makes the question moot.

6. **The preference is the device's, and the phone's default is AAC.** ADR-0029 keeps listener
   preferences off the server; this is one. `familiar-apple` stores it in `UserDefaults` beside the
   other download settings ADR-0025 put on the phone's Settings screen, as a two-way choice:
   *Smaller files (AAC)* or *Original quality*. The phone defaults to the first. The Mac defaults
   to the second and does not show the control: it is the management surface (ADR-0013), disk is
   not scarce there, and the Mac is where someone would want the archive copy.

7. **The client sends the parameter from `DownloadManager` only.** The player's stream URL is
   untouched; playback continues to fetch the original. This keeps the change to one code path,
   the one that already differs from playback by a header, and it keeps the offline set
   *smaller* than what was streamed rather than different in kind. Cellular streaming at AAC is
   the obvious next use of the same parameter and is deliberately not this decision (see
   Consequences).

8. **A cached original is not promoted to a download when the preference is AAC.** ADR-0010 point
   6 promotes a play-cached file to the pinned set rather than re-fetching, on the argument that
   the bytes are already on the device. That argument is about the network; this preference is
   about disk. A 35 MB FLAC promoted into the permanent set on a phone whose owner asked for
   smaller files is the thing they asked not to have, and it would be the one file in the offline
   set that does not match the setting. So promotion checks the cached file's format against the
   preference — a lossy original, or a preference of *Original*, promotes as before — and
   otherwise falls through to a fresh fetch, leaving the cached original evictable as it was.

9. **Existing downloads are left alone.** A phone that already holds FLAC downloads keeps them;
   nothing re-fetches on upgrade, because a silent 8 GB re-sync on the first launch after an
   update is a bulk download nobody asked for — the shape of both incidents. A *Re-download in smaller
   files* action on the Downloads screen, which removes the pinned lossless files and queues them
   again, is the follow-up that lets someone reclaim the space on purpose.

## Alternatives Considered

- **Transcode on the phone after download.** Fetch the FLAC, encode with `AVAssetExportSession`,
  delete the original. Rejected: it spends the network and the NAS's disk on the bytes this
  decision exists not to move, and background `URLSession` downloads complete while the app is
  suspended, when there is nothing to run an encoder. The saving would be disk only, which is the
  smaller of the two problems.

- **A separate `/tracks/{id}/download` endpoint.** Cleaner in the OpenAPI document. Rejected
  because it duplicates a route whose only difference is a codec, and because ADR-0007 point 8
  keeps streaming out of the generated client — a second hand-built URL is a second place to get
  a Range request wrong. One endpoint, one parameter.

- **Server-side preference, so the web app and the phone agree.** Rejected by ADR-0029: the server
  stores no listener preferences, and this one is about a device's disk, which the server has no
  view of. The web app does not download.

- **Encode ahead of time — every lossless favourite, in a background job.** The first sync would be
  instant. Rejected for now: it doubles the disk the NAS spends on favourites before anyone asks,
  and the cache-on-demand path reaches the same steady state after one sync. Worth revisiting if
  the first-sync experience turns out to matter more than expected (Consequences).

- **192 kbps, or VBR.** Smaller. Rejected as a default: the saving over 256 is a fifth of an
  already small file, and a fixed rate makes the size of a sync predictable from its duration,
  which the plan uses. VBR is a reasonable later option behind the same parameter.

- **Opus.** See point 3. The container problem is disqualifying on iOS.

## Consequences

- **Positive, and the point.** A lossless favourite on the phone costs a quarter of what it did:
  the 30.5 GB of partials in the September incident would have been under 8 GB, and every
  `/stream` a sync makes holds its worker for a quarter of the bytes. The phone's offline set
  stops being bounded by the size of Bandcamp purchases.

- **Positive.** Lossy sources are byte-identical to today, on every device. Nothing about this
  change can degrade a file that was already lossy.

- **Positive.** Playback is untouched. Anyone who wants to hear the FLAC hears the FLAC; the
  archive is where it always was.

- **Tradeoff, and the one to watch.** The first sync after this ships is roughly six core-hours of
  ffmpeg on the NAS, spread over the sync at up to four cores. That is the same box, under the
  same kind of load, as the two incidents — on CPU this time rather than the spindle. Point 5's
  semaphore is the bound; whether four is right is a guess informed by one encode on an idle
  machine, exactly as ADR-0112's twelve was. Watch load and the file-response limiter's counters
  during the first real sync, and lower it if the API gets slow.

- **Tradeoff, taken.** A sync request holds a file-response slot while it waits for an encoder
  (point 5). During a first sync this reduces effective sync concurrency to whatever the encoder
  bound allows; after it, the cache makes the wait zero. Accepted over refusing, for the reason in
  point 5.

- **Tradeoff.** `data/transcode_cache` grows by roughly a quarter of the lossless library's size,
  over time, as tracks are downloaded. It is a cache — it can be deleted and rebuilds — but nothing
  evicts it. A size cap or LRU is a follow-up if it ever matters; at 9 MB a track it is a long way
  from mattering.

- **Risk, named.** Point 2 means a client asking for `?format=aac` may receive an MP3, and a client
  that names the file from the request rather than the response would store an MP3 as `.m4a`.
  `familiar-apple` names from the response today; the test for point 2 on the client side should
  assert that specifically, because it is the kind of thing a refactor silently loses.

- **Not decided here: streaming at AAC on cellular.** The same parameter serves it and the player
  is the only other caller of the stream URL. It is left out because it changes what is *heard*
  rather than what is stored, and because the play cache would then hold two formats of one track.
  A separate decision, when someone asks for it.

- **Follow-up.** The *Re-download in smaller files* action from point 9.

- **Follow-up.** Report the encoder semaphore's high-water mark and wait count beside ADR-0112's
  counters — and put both in `/health`, which is ADR-0112's own still-open follow-up.
