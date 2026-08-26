# ADR-0086: Music Videos Become a Persisted Resource

Status: accepted

Date: 2026-08-18

Extends [ADR-0007](ADR-0007-clients-are-generated-from-openapi.md), whose generated surface this
adds five operations to, and whose point 8 it applies to the one handler that stays outside.
Prerequisite for
[ADR-0085](ADR-0085-music-videos-are-a-mac-function-not-a-visualizer.md) — **this one executes
first**, on the principle that server-side work every client inherits comes before client work.

## Context

Music video support has been in the product since Phase 5 and was never removed. That is worth
stating because it has already been got wrong once:
[ADR-0055](ADR-0055-the-site-is-restructured-around-five-things.md) lines 50–55 record an audit that
concluded the support had been deleted, on a grep that used the wrong term. What was removed is a
row on the website's comparison table (`docs/SITE-CLAIMS.md:101`), not the feature. The router is
mounted at `app/main.py:514`.

What exists, verified at write time:

- `app/api/routes/videos.py` (254 lines) — five operations under `/videos`, all keyed by track:
  `search`, `status`, `download`, `stream`, `delete`.
- `app/services/video.py` (280 lines) — yt-dlp search and download, one file per track at
  `settings.videos_path` (`app/config.py:41`, default `data/videos`), already in the S3 backup set
  (`app/services/s3_backup.py:312`).
- `TrackVideo`, table `track_videos` (`app/db/models/tracks.py:339`) — `source`, `source_id`,
  `source_url`, `file_path`, `is_audio_only`, `file_size_bytes`, `video_metadata`,
  `match_confirmed_by`, `downloaded_at`, `last_played_at`, with a unique constraint on
  `(track_id, source, source_id)`.

Three findings make this ADR necessary rather than optional, and all three were checked rather than
assumed:

1. **`videos` is not in the generated surface.** `scripts/lint_openapi.py:59` lists eleven vendored
   tags and `videos` is not among them, so a generated client cannot reach these operations at all.
2. **`track_videos` is orphaned, and on some databases it does not exist at all.** It is declared
   and exported (`app/db/models/__init__.py:39`), and **nothing in the application reads or writes
   it**. No migration file in `migrations/versions/` contains the string `video` at all; fresh
   databases get the table only because the baseline runs `Base.metadata.create_all()`
   (`migrations/versions/20241231_000000_baseline.py`). **A database stamped at baseline before this
   model landed therefore has no `track_videos` table**, and nothing would report that:
   `tests/test_migrations.py:101-124` records that the baseline test "cannot detect schema drift, and
   used to claim it could", and the incremental check only compares post-baseline DDL. So this is not
   only a table nobody uses — it is a table whose existence is unverified. The service's own
   `VideoDownloadStatus` is an unrelated in-memory dataclass whose similar name is the reason the
   whole thing is easy to miss.
3. **The stream handler advertises range support it does not implement.** It sets
   `Accept-Ranges: bytes` and then reads the file from byte 0 on every request; the `Range` request
   header is not parsed anywhere in the file. A player that seeks gets the whole file again from the
   start.

A fourth fact shapes the scope: **download state lives only in process memory.**
`VideoService._downloads` is a `dict` (`app/services/video.py:43`) populated by `set_pending` and
the download coroutine, and the download itself runs in FastAPI `BackgroundTasks`. A restart loses
every in-flight download and every record of which YouTube video a file came from — `has_video()`
is a check that `{track_id}.mp4` exists on disk, and nothing more.

The consequence that matters for `ADR-0085` is that **there is no way to ask which tracks have
videos.** Every operation is keyed by a track id you already have. A destination that lists them has
nothing to call.

There are **no functional tests for this feature** on either side. The only test that mentions
`/videos/` is `tests/test_contract_error_shapes.py`, which asserts an error envelope.

## Decision

1. **`track_videos` becomes the record of what was downloaded.** A completed download writes a
   `TrackVideo` row — `source` (`youtube`), `source_id`, `source_url`, `file_path`,
   `file_size_bytes`, `downloaded_at`, and the yt-dlp metadata worth keeping in `video_metadata`.
   The columns already exist and are adequate, so this is a service that starts using its table
   rather than a schema change — but it still needs **a real migration**, guarded with
   `table_exists` from `migrations.helpers`, because of the second finding above: the table is
   present only on databases built by the baseline's `create_all`. `delete_video` removes the row
   with the file.

2. **`has_video` and `get_download_status` resolve against the database first.** The in-memory dict
   stays as the progress cache for a download that is currently running — that is what it is good
   at — but a restart no longer erases the fact that a video exists, and "which video" becomes
   answerable. Where the two disagree, the file on disk wins for existence and the row wins for
   identity; a row whose `file_path` is gone is deleted rather than reported.

3. **`GET /videos` lists tracks that have a video**, paged, ordered, returning enough to draw a row
   — track id, title, artist, the source id, and `downloaded_at`. This is the operation
   `ADR-0085`'s destination is built on, and it is the one thing the current surface cannot do.

4. **`GET /videos/{track_id}/stream` honours `Range` by calling `stream_file`, and does not parse
   anything.** `app/api/streaming.py:12-54` already exists and already does this, by handing the file
   to Starlette's `FileResponse`, which reads the range off the ASGI scope and supplies `206`, `416`,
   suffix ranges, multipart, `ETag` and `Last-Modified`. `/tracks/{id}/stream` calls it
   (`routes/tracks/streaming.py:133`). **Writing a second range parser here is specifically
   forbidden**: `stream_file`'s docstring catalogues the five defects of the hand-rolled parser it
   replaced — blocking I/O on the event loop, silent truncation under a `Content-Length` that
   promised more, no validators, suffix ranges served from the wrong end, and multipart raising
   `ValueError` — which together caused issue #13, playback dying a couple of times per seven minutes
   of listening. The handler also declares its media type honestly, mirroring
   `routes/tracks/streaming.py:65-83` with `video/*`, so the schema stops claiming
   `application/json`.

   **`release_connection(db)` stays exactly where it is** — the comment above it records why, and it
   is the fix for a defect that turned 834 downloads into 83-byte error bodies: a `yield` dependency
   otherwise holds a database connection for the length of the video.

5. **The five JSON operations join `VENDORED_OPERATIONS`; the `videos` *tag* does not join
   `VENDORED_TAGS`.** This is the ADR-0031 precedent, not a stylistic choice, and the reason is
   mechanical: the generator's filter keys are a **union**, so naming the tag would re-admit
   `videos_stream_video` along with the rest. `search`, `status`, `download`, `delete` and the
   new `list` are ordinary JSON and are generated; the stream is written by hand, because `AVPlayer` is the caller
   and range requests are what ADR-0007 point 8 excludes.

   **Point 8 is doctrine with no enforcement, and this ADR should not pretend otherwise.**
   `/tracks/{id}/stream` is *not* filtered out by `scripts/lint_openapi.py` — it carries the `tracks`
   tag and is fully in scope, passing the lint only because point 4's `response_class` and explicit
   `responses` stop it advertising `application/json`. The only mechanism that expresses "generate
   five of six" is the per-operation list. Adding it also obliges deleting the video stream's entry
   in `ALLOWED_UNTYPED_OPERATIONS` (`scripts/lint_openapi.py:235`): point 4 makes the handler typed,
   and an allowlist entry for an in-scope operation is a contradiction the lint fails on by design.

6. **The video stream is media, and inherits ADR-0045's media exemption.** That ADR decided on
   2026-08-09 that artwork and audio streams are exempt from the authentication gate, because a
   media element cannot send a header and a cast target holds no credential. A video element is the
   same case. This is recorded so it is not re-litigated when point 5 of that ADR ships, and so
   nobody adds a profile header to an `AVURLAsset` to work around a gate that does not apply.

7. **Every point above gets a test.** The feature has none today, which is why three of the findings
   in `## Context` survived this long: range correctness (a `206` with the right `Content-Range` and
   the right bytes, and a `200` without the header), the list endpoint's shape, and a download that
   writes its row. Point 5 largely tests itself: `lint_openapi.py` fails when the generated surface
   and the schema disagree, and the Swift generator throws on an operationId that does not exist, so
   a typo there is a build failure rather than a silent omission.

## Alternatives Considered

**Leave the endpoints un-vendored and hand-write all five calls in Swift.** Tempting because the
stream has to be hand-written anyway, so the split feels like an inconsistency. Rejected because
ADR-0007's carve-out is specifically about *bodies generated clients handle badly* — range requests
and SSE — and search results, status and a paged list are ordinary JSON. Hand-writing them buys a
false tidiness and gives up the schema check that catches a response shape changing underneath the
client.

**Move the download to the Redis worker system** (`app/services/background.py`, `tasks.py`) instead
of `BackgroundTasks`. Genuinely better for a long download that should survive a deploy, and
rejected here on scope: it is a decision about where background work runs, it would apply to more
than videos, and `BackgroundTasks` is adequate for one user-initiated download of a few minutes.
Making the record durable (point 1) removes the sharp edge — a lost in-flight download is now
visibly incomplete rather than invisibly forgotten.

**Write the range parser by hand, as the ADR originally said.** The obvious reading of finding 3
is "the handler ignores `Range`, so make it read `Range`". Rejected once `stream_file` was found:
the audio stream solved this exact problem, and the incident it caused (issue #13) is written into
that helper's docstring precisely so the next person does not solve it again. Recorded because the
first draft of this ADR made that mistake.

**Keep file existence as the source of truth and answer `GET /videos` with a directory scan.**
Cheapest possible list endpoint, and it works, since the filenames are track ids. Rejected because
it cannot answer *which* video is attached, which is what a re-match needs, and because it makes the
orphaned table permanent — a schema that describes something the code refuses to use is worse than
no schema at all.

**Add `has_video` to the track model's serialisation instead of a list endpoint.** Would let any
existing list filter on it with no new operation. Rejected: it puts a per-track filesystem or join
cost on every track response in the app to serve one screen, and the filter belongs where the
question is asked.

## Consequences

- **Positive** — the Mac can ask what has a video, which is the single blocker on `ADR-0085`'s
  destination.
- **Positive** — `AVPlayer` can seek, and so can any browser `<video>` element; the header stops
  being a promise the handler breaks.
- **Positive** — a table that has been declared, exported and unused becomes load-bearing, and the
  `(track_id, source, source_id)` unique constraint starts doing the job it was written for.
- **Positive** — the table stops being conditional on how a database was built. Point 1's migration
  is the first thing that guarantees `track_videos` exists on a database older than the model.
- **Positive** — the first functional tests this feature has ever had.
- **Tradeoff** — **point 5 cannot land on the backend alone.** `surface_disagreement()` compares
  `VENDORED_OPERATIONS` against the Swift config for anyone with both repos checked out, so adding
  the five operations here fails `make lint-contracts` until `familiar-apple`'s
  `openapi-generator-config.yaml` names the same five. That is the mechanism working — it is what
  makes ADR-0014 point 4's "updated in the same change" enforceable — but it means the `familiar-apple`
  half is not optional follow-up. **And the config change cannot land there alone either**: the
  generator throws on an operationId its vendored `openapi.json` does not contain, so the schema is
  re-vendored in the same commit. ADR-0078 point 2 says that copy is made by a target rather than by
  hand; no such target exists yet, which is worth knowing before reaching for `cp`.
- **Tradeoff** — the generated Swift surface now has a second entry that is a *list of operations*
  rather than a tag, so the two mechanisms sit side by side and someone will eventually add `videos`
  to `tags:` for tidiness and silently re-admit the stream. The config file warns about this in
  ADR-0031's own comment; point 5 repeats it for a reason.
- **Tradeoff** — existence is now answered from two places (a row and a file) and they can disagree.
  Point 2 states which wins for which question rather than leaving it to be discovered.
- **Tradeoff** — a download that dies with the process still leaves no row, so it looks like a
  download that never started. Better than the current behaviour, but not the same as durable.
- **Follow-up** — moving the download to the worker system, if a video that survives a deploy turns
  out to matter.
- **Follow-up** — `is_audio_only`, `match_confirmed_by` and `last_played_at` stay unused after this
  ADR. They are not removed, because `ADR-0085`'s match-and-download action is the natural caller
  for `match_confirmed_by`; if it ships without one, they should go.
