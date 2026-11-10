# ADR-0176: Media Is Authorized by Header, Cookie or Signed URL

Status: accepted

Date: 2026-11-09

Implementation:

- **Phase 1, 2026-11-09: the oracle is closed.** `backend/app/services/artwork_keys.py` issues a
  derivable hash key as `<hash>.<mac>` (HMAC-SHA256 truncated to 64 bits, keyed by
  `artwork_key_secret`, minted on first use into `settings.json` and left out of the settings view
  entirely) and accepts only that form or an album UUID. `GET /artwork/{key}/{size}` and
  `GET /artwork/status/{key}` answer a bare or wrongly-MAC'd hash with the same 404 as missing art;
  `/artwork/queue`, `/artwork/queue/batch` and `/artwork/regenerate` hand out the issued form, and
  `/artwork/status/batch` reports an unissued key as failed so a client stops polling it. Files on
  disk keep their names. **Found while building:** `MEDIA_ROUTES`' pattern
  `^/api/v1/artwork/[^/]+/[^/]+$` also matches `/artwork/status/{hash}`, a second unauthenticated way
  to ask whether a guessed album exists; it takes only issued keys now too. No client change: the
  web app takes keys from the queue responses and keeps them in memory only, and the Apple app does
  not use these routes. `tests/test_artwork_keys.py`: a derived hash is refused by both routes while
  the file exists, the issued key and a UUID are served, tampered and path-shaped keys are refused,
  the secret is minted once and never shown; the route tests fail against the previous routes. The
  two stale comments named under Follow-up (`MEDIA_ROUTES`, `api/base.ts`) are corrected.
- **Phase 2, 2026-11-10: all three credentials are accepted, none required.**
  `backend/app/api/media_credentials.py` checks a media read for the token header, a media cookie or
  a signed URL, every key derived from the server token so rotation re-keys all three (point 5). The
  gate's check (`TokenAuthMiddleware._media_refused`) is written and tested but switched off by
  `MEDIA_ENFORCED = False`; Phase 4 flips it. `POST /auth/media-cookie` issues the cookie behind the
  token gate (`HttpOnly`, `SameSite=Strict`, `Path=/api/v1`, a month, `Secure` only over https,
  since the tailnet is plain http); `DELETE` clears it. `POST /outputs/{id}/play` hands a speaker
  `?exp=&sig=`, the HMAC over method class, routed path and `exp`. **`exp` measured, per the
  follow-up:** the longest track on the NAS on 2026-11-10 was 11,626 s and 97 ran over an hour, so a
  URL lasts its own track plus four hours (eight when the length is unknown) rather than one fixed
  span. `RedactCredentialsFilter` on `uvicorn.access` and `redact_credentials` on the UPnP failure
  log keep `sig` out of logs (point 6). The server advertises `media.credentials` (point 8).
  `tests/test_media_credentials.py` runs the exit condition with enforcement on: each credential reads
  media; none, a wrong token, a rotated cookie or signature, the token used as a cookie and an expired
  signature are refused; a cookie on a `POST` or a non-media path and a signature for another path
  authorize nothing; a tokenless server is left to ADR-0171; and, with enforcement off as shipped,
  media is still served bare.
- **Phase 3, web and server side, 2026-11-10.** The web admin and `/embed` ask for the cookie once
  the token is loaded, and whenever it is set or cleared (`syncMediaCookie` in `api/base.ts`). The
  visualizer page cannot use the cookie (its origin is the app's own scheme), so `EmbedVisualizer`
  fetches the artwork with the header and hands the plugin a `data:` URL. **Apple side:**
  `familiar-apple` #267: one rule, `MediaAuthorization`, sends the header only to the paired server's
  scheme, host and port, reading the token per request, from the engine's load, preload and
  lock-screen artwork, `ArtworkFetcher`, `DownloadManager` and the video `AVURLAsset`. An App Store
  release carrying it is what starts point 8's clock.
- **Found while building:**
  - **Nothing calls the speaker route.** The web player that called `POST /outputs/{id}/play` was
    retired, the Apple app never used it, and no MCP tool reaches it, so signing is built and tested
    but has no live consumer today. It is kept because the route still exists.
  - **The Context table misses one consumer:** `NativeAudioEngine`'s lock-screen artwork fetch of
    `/tracks/{id}/artwork`, now covered.
  - **A background download queued before a rotation keeps the old token**, held by the system with
    the task's other headers. Once enforced it fails until retried; point 4 forbids the token only in
    a URL or `DownloadTaskDescription`, which this respects.
- **Not done:** Phase 4 (enforce, `Cache-Control: private`, remove the health-register entry) waits for
  point 8's trigger: 1.6 and 1.7 (build 78) send no credential on media and are still offered.

Extends [ADR-0171](ADR-0171-a-remotely-reachable-server-is-protected-by-default.md) and
[ADR-0045](ADR-0045-familiar-authenticates-inbound-requests.md)

## Context

ADR-0171 points 5 and 6 left media for this record. `MEDIA_ROUTES` in `backend/app/api/auth.py`
exempts `GET`/`HEAD` on seven route shapes from the token gate, so on a tokened server anyone who
can reach the port can fetch a stream or a picture whose URL they know or can construct.

ADR-0045 exempted media for two reasons. **One no longer holds.** Its "guest listeners" joined
through `sessions.py`'s `join_guest` with a spoken six-character code and held no token. That code
is gone: nothing under `backend/app` defines or calls `join_guest`. What is left is the consumers
that really cannot send a header, and those that could but don't:

| Consumer | Routes | Can it send a header? |
|---|---|---|
| Network speakers: Sonos `play_uri`, UPnP/WiiM `SetAVTransportURI`, AirPlay `play_url`, Chromecast `play_media` (`backend/app/services/outputs.py`) | track stream | **No.** A third-party device fetches the URL itself |
| Web admin `<img>` (`AlbumArtwork.tsx`, `DiscoveryCard.tsx`, `ProfileSelector.tsx`, `ProfileSettings.tsx`) | artwork, artist image, avatar | **No header**, but it is same-origin with the server |
| Apple `NativeAudioEngine` (`URLSession.downloadTask(with: URL)`), `ArtworkFetcher` (`session.data(from:)`), `DownloadManager` (`URLRequest`, already sets `X-Familiar-Intent`) | stream, artwork, video poster | **Yes.** Each owns its session or request; none sends the token today |
| Apple `AVPlayerItem(url:)` for music videos (`MusicVideoBackdrop.swift`) | video stream | Yes, through `AVURLAsset`'s header option, deliberately not used today |
| Sandboxed visualizer pages, paired clients since ADR-0164 | stream, artwork (CORS allows `Origin: null` on those paths, `backend/app/main.py`) | Yes: they hold the token for the API already |

What the exemption leaks is narrower than ADR-0045 recorded. Stream, video and avatar URLs are
keyed by v4 UUIDs, which cannot be enumerated while the rest of the API is closed. The album
artwork key is `canonical_album_id`, also a UUID, whenever the track has one (`album_key_for_track`,
`backend/app/services/artwork.py`). **The derivable `sha256(artist::album)[:16]` is only the
fallback for tracks the album resolver could not place**, and the comment above `MEDIA_ROUTES`
still describes it as the key. That fallback is the oracle: anyone can compute it for a guessed
album and ask whether this library has it.

Three facts constrain any scheme:

- **A speaker holds one URL per track.** The server sends no next-track URI and no queue: every
  output's `play` replaces the current one, and the client sends a new `play` per track. A URL must
  stay valid for one track's playback, plus the device's own re-fetches and range requests.
- **Clients cache by URL.** The Apple app's `URLCache` is 512 MB on disk, keyed by URL. Artwork is
  served `Cache-Control: public, max-age=31536000`. A URL that changes every request defeats both.
- **Query strings reach the log.** `uvicorn.access` logs at INFO (`backend/app/logging_config.py`),
  path and query included.

Old clients matter too. The Apple app 1.6 and 1.7 (build 78) send no token on any media route, and
both will be on phones for months.

## Decision

1. **A media request is authorized by any one of three credentials:** the server token in the
   header, as on the rest of the API; a media cookie, for the web admin's `<img>`; or a signed URL,
   for a consumer that can do neither. With no token configured, ADR-0171's exposure rules apply
   unchanged.
2. **Signed URLs are minted by the server, for speakers only.** `outputs` signs the URL it hands a
   device: `?exp=<unix>&sig=<hmac>`, where the HMAC covers method class, path and `exp` (never the
   `Range`), keyed by a key derived from the server token. `exp` is long enough for the longest
   track plus a margin, measured rather than guessed. Clients never sign, so no client can mint a
   URL for a path it was not given.
3. **The web admin gets a media cookie at sign-in:** `HttpOnly`, `SameSite=Strict`, path-scoped to
   `/api/v1`, honoured **only** for `GET`/`HEAD` on media routes. It authorizes reading pictures,
   never an action, so it opens no cross-site-request route. Artwork URLs stay stable, so the browser
   cache keeps working.
4. **Apple clients send the header** from `NativeAudioEngine`, `ArtworkFetcher`, `DownloadManager`
   and the video `AVURLAsset`. Their URLs stay the same, so `URLCache`, the play cache and saved
   download tasks are unaffected. The token is never put in a URL that is persisted, including
   `DownloadTaskDescription`.
5. **Rotation revokes all three.** Rotating the token re-keys signatures and invalidates cookies, the
   same as it signs clients out. A speaker mid-track may fail its next range request; that is the
   cost of revocation working.
6. **Credentials stay out of logs and shared caches.** `sig` is redacted from access logs and from
   any URL Familiar logs itself. Media served to an authorized caller is `Cache-Control: private`
   once enforcement is on, so a shared proxy cannot serve one listener's library to another.
7. **The artwork oracle closes first, on its own.** Where the key would be the derivable hash, the
   server issues `<hash>.<mac>` instead, the MAC keyed by a server secret, and the route accepts a
   hash only with a valid MAC. Album UUID keys are unchanged. The server can still compute and
   verify the key without a lookup table, and an outsider can no longer compute it. Clients already
   take the key from the server (`/artwork/queue` responses; neither client reproduces the hash), so
   this lands before any enforcement and needs no client change.
8. **Enforcement waits for the clients, and says so.** The server advertises a `media.credentials`
   capability (ADR-0168) as soon as it accepts all three credentials. It enforces them on a tokened
   server only when no App Store build that omits the header is still offered, the same trigger
   `compat.py` uses for its aliases. Until then media stays exempt, and `docs/HEALTH.md` says so.

## Phased Delivery

1. **Oracle:** point 7, with a test that a bare derived hash returns 404 while the issued key works,
   and that artwork for a track with no `canonical_album_id` still loads in the web admin.
2. **Accept:** the server accepts header, cookie and signature on media routes, without requiring
   them yet. Speakers get signed URLs. Logs are redacted.
3. **Send:** the Apple clients send the header and the web admin gets its cookie. An Apple release
   ships this.
4. **Enforce:** once the trigger in point 8 is met, media on a tokened server requires a credential,
   `MEDIA_ROUTES` becomes "media routes, credential by any of three", and the health-register entry
   is removed.

**Exit condition:** on a tokened server, a media request with no credential is refused; a speaker,
the web admin, an Apple client and a visualizer page each still play and show artwork; rotation
stops all four until they re-pair; and no credential appears in a log line.

## Alternatives Considered

**Signed URLs for everything.** One mechanism is simpler to explain. Rejected because every URL a
client caches would change with each expiry, so `URLCache`, the browser cache and the Apple play cache
would all miss, and saved background-download tasks would hold URLs that expire before the system
runs them. The consumers that can send a header gain nothing from a signature.

**A second, media-only static token in the query string.** No expiry logic. Rejected because it
would be written to access logs, browser history and speakers' own logs, would never expire, and
would be a long-lived credential sitting in URLs: the thing point 6 exists to prevent.

**Only close the artwork oracle (point 7) and stop.** The stream, video and avatar URLs are already
unguessable UUIDs, so this closes the one enumerable leak for almost no cost. Rejected as the whole
answer because a UUID URL is a credential with no expiry and no revocation: one that reaches a log, a
speaker or another person works for ever, and rotating the token does not stop it. It is kept as
Phase 1 because it is worth doing first.

**Gate media with the header now.** Rejected for the reason ADR-0171 already gives: speakers cannot
send it, and every shipped Apple build would lose audio and artwork at once.

## Consequences

- **Positive:** media gets the same revocation as the rest of the API, and the enumerable leak
  closes before anything else.
- **Positive:** URLs that clients cache stay stable, so no cache, play cache or saved download is
  disturbed.
- **Tradeoff:** three credentials on one set of routes are more to test than one; the matrix in
  `tests/test_exposure.py` grows a media axis.
- **Tradeoff:** a speaker's URL can outlive a rotation only until it expires, and can fail mid-track
  when one happens.
- **Tradeoff:** enforcement is gated on old app builds leaving the store, so the exemption stays for
  months after Phase 3.
- **Follow-up:** measure the longest track and a speaker's re-fetch behaviour before fixing `exp`.
- **Follow-up:** fix the stale comment above `MEDIA_ROUTES` (key derivation) and the one in
  `packages/frontend/src/api/base.ts` that cites `WebAudioEngine.ts`, which no longer exists.
