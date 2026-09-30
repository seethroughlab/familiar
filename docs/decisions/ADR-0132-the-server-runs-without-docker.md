# ADR-0132: The Server Runs Without Docker

Status: accepted

Date: 2026-09-29

Implementation:
- **2026-09-29, `familiar`: points 2–6.** Point 8 shipped separately (below), because it changes
  `release.yml` and adds a download path of its own. Point 7 needed no code.
  - **Point 2.** `Settings.data_dir` is read from `FAMILIAR_DATA_DIR` only. `populate_by_name` stays
    off, because with it on pydantic-settings also reads a bare `DATA_DIR`, and a test pins that.
    `art_path`, `videos_path`, `profiles_path` and `mixtapes_path` default under it through
    `default_factory`, so `ART_PATH` and the others still win. The nine working-directory sites
    outside `config.py` now read `settings_file`, `outputs_file`, `transcode_cache_dir`,
    `restore_safety_dir`, `analysis_data_dir` and `models_dir`. `scripts/lint_data_paths.py` runs in
    `make lint-contracts` and CI, and it reports all nine against the old sources.
  - **Point 3 is built differently from its text.** It reads a `VERSION` file beside `app/`
    (`BACKEND_ROOT / "VERSION"`), not `importlib.metadata`. In the image that path *is*
    `/app/VERSION`, so nothing moved. Metadata was wrong for two reasons: every checkout has
    `familiar 0.1.0` installed, and the update checker skips only the literal `"dev"`. A
    development server would have been told a release was waiting. A native packager writes the
    file, as the Dockerfile does.
  - **Point 5 was already true, and this ADR's Context was wrong about it.** The baseline migration
    (`20241231_000000_baseline.py`) runs `CREATE EXTENSION IF NOT EXISTS` for `vector` and
    `pg_trgm`, and nothing uses `uuid-ossp`. No migration was added. Proved on a new, empty
    pgvector database: `app.serve.migrate()` run from outside `backend/` reaches
    `20260831_seed_listenbrainz` with both extensions and 25 tables.
  - **Point 6.** `python -m app.serve [--host] [--port]`, defaulting to `127.0.0.1:4400`. It is
    migrate, then uvicorn with one worker, with both steps injectable for tests. It was started from
    a scratch directory with `FAMILIAR_DATA_DIR` set: `/api/v1/health` answered `healthy`, the
    socket was bound to 127.0.0.1 only, and a settings write landed in the data directory.
  - Tests: `tests/test_server_without_docker.py` and `tests/test_lint_data_paths.py`.
- **2026-09-29, `familiar`: point 8.**
  - **The export is deterministic, which is what lets the hashes live in source.** Hashed straight
    from the registry, without pulling the images: `clap_audio.onnx` (117,275,257 bytes) and
    `clap_text.onnx` (501,448,656) are byte-identical in v0.2.0-beta6 amd64, v0.2.0-beta7 amd64 and
    v0.2.0-beta7 arm64. `app/services/clap_artifacts.py` pins both. `clap_audio_fp16.onnx` is *not*
    reproducible (beta6 and beta7 differ) and nothing loads it, so it is not published.
  - **Context overstated the files.** There is no `clap_text.onnx.data`: at 501 MB the text
    encoder is one file. `tokenizer.json` is not an export artifact either. `clapback_embed`
    fetches it from Hugging Face at first use, in the image as well, so it was left alone.
  - **Release.** The smoke test runs `python -m app.services.clap_artifacts verify` inside the
    built image on both architectures. The amd64 job copies the two files out with `SHA256SUMS`,
    and `create-release` attaches all three. The Dockerfile fetches `export_models.py` from
    clapback's `main` unpinned, so this check is also what catches an upstream change that moves
    the output: the release fails instead of every vector moving.
  - **Server.** `configure_model_dir()` sets `CLAPBACK_MODEL_DIR` to `data_dir/models/clapback`
    unless the image already has, before any pool spawns. `ensure_present()` runs as a startup
    task: in Docker it is two `stat` calls. A `dev` server only logs, having no release to fetch
    from. A released server downloads from its own tag to `.part` and renames only on a hash
    match. Until the files land, `_models_missing()` keeps embedding off, in capabilities, both
    extractors and the embedding queue, the same as `DISABLE_CLAP_EMBEDDINGS` rather than failing
    each track.
  - Proved with the real bytes: the published beta7 encoders pass `verify`, and `download()` into
    an empty data directory, from a local server standing in for GitHub, fetched, verified and
    placed both. Tests: `tests/test_clap_artifacts.py`.

Extends [ADR-0131](ADR-0131-the-server-is-its-own-app.md)

## Context

ADR-0131 gives the server a second form beside Docker: Familiar Server, a Mac app. Today the only
way to get a server is Docker. This ADR is the server-side precondition for everything else in that set:
- the server has to run as an ordinary process before Familiar Server can carry it (ADR-0136)
- it has to run without Redis before it is one supervised thing rather than three (ADR-0133)

Investigation found that the server is much closer to running natively than the install
instructions suggest:

- **The process model is already portable.** `app/main.py` forces the `spawn` start method at
  import. The analysis, on-demand and scan pools use spawn contexts with top-level, picklable
  entry points (`services/background/executors.py`, `services/tasks/library_sync.py`). The code
  has no `os.fork`, signals, `fcntl` or inotify. The two Unix-only calls, `os.nice` in the pool
  initialiser and `resource` in `tasks/common.py`, are each inside a `try`.
- **The runtime no longer carries torch.** Since ADR-0105, CLAP runs on ONNX through
  `clapback-embed`. torch exists only in the Dockerfile's `onnx-export` stage.
- **What does assume a container** is a small set of paths and one executable lookup:
  - `get_app_version()` reads `/app/VERSION` (`app/config.py:9`).
  - `music_library_path` defaults to `/music` (`app/config.py:33`), and the startup warning tells
    the user to configure it "in docker-compose.yml" (`app/main.py`).
  - Thirteen state paths are relative to the working directory, which only works because the image's
    `WORKDIR` is `/app` and `/app/data` is a volume:
    - `data/settings.json` (`services/app_settings.py:169`, and three more times in
      `services/s3_backup.py`)
    - `data/outputs.json` (`services/outputs.py:33`)
    - `data/transcode_cache` (`api/routes/tracks/streaming.py:176,248`)
    - `data/restore-safety` (`services/s3_backup.py:691`)
    - `data/analysis` (`services/track_analysis/constants.py:15`)
    - `data/art`, `data/videos`, `data/profiles` and `data/mixtapes` (`app/config.py:44-47`)
  - `services/vocal_detection.py` locates `silero_vad.onnx` relative to its own source file.
  - `ffmpeg` and `ffprobe` are invoked by bare name (`services/artwork.py`, `flac_remux.py`,
    `mixtape_export.py`, `video.py`, `api/routes/tracks/streaming.py`), so they resolve through
    `PATH`.
  - Database extensions are created by `docker/init-pgvector.sql` (`vector`, `uuid-ossp`,
    `pg_trgm`) and by `docker/entrypoint.sh` (`vector`), not by migrations.
- **The CLAP artifacts are built, not downloaded.** The Dockerfile's comment above the export stage
  explains why: the two files (112 MB audio, 502 MB text) are "reproducible from the pinned
  checkpoint rather than trusted from a URL". A native install has no export stage, so this ADR
  has to say where they come from without discarding that reasoning.

**Premise examined and dropped: port the database to SQLite so there is nothing to install.** This
does not survive a count:
- pgvector: an HNSW index and 8 `cosine_distance` call sites
- `pg_trgm` GIN indexes
- `on_conflict_do_*` upserts at 6 sites
- 61 raw `text()` calls
- at least 22 of the 53 migrations name JSONB, `postgresql` dialect types, extensions or `DO $$` blocks

ADR-0128 rejected SQLite for tests on the same grounds. The native server keeps PostgreSQL 16 with
pgvector, supplied by whoever packages it.

## Decision

1. **The server runs as an ordinary Python process with no container.** Docker stays the supported
   path for the NAS and Linux, and nothing is removed from it. A native distribution (the first is
   ADR-0136) is a second way to run the same code, not a fork of it.

2. **One data directory anchors all server state.** `Settings.data_dir`, set by `FAMILIAR_DATA_DIR`,
   defaults to `Path("data")`, so the container's `/app/data` is unchanged. Every path listed in
   Context resolves against it, including the silero model and the transcode cache. A path given
   explicitly by its own variable (`ART_PATH` and the others) still wins. `app/config.py` is the one
   place these paths are derived, and a boundary lint forbids new bare `Path("data/…")` literals
   under `app/`.

3. **The version comes from package metadata.** `get_app_version()` reads
   `importlib.metadata.version("familiar")`, with `/app/VERSION` checked first so the image keeps
   its build-time stamp. The release workflow stamps the same version into `pyproject.toml` that it
   writes to `VERSION`.

4. **The library path has no container default outside the container.** The startup warning names
   the setting rather than a compose file. A native distribution sets `MUSIC_LIBRARY_PATH` from the
   folder the user chose.

5. **Migrations own the extensions they depend on.** A new migration runs
   `CREATE EXTENSION IF NOT EXISTS` for `vector`, `uuid-ossp` and `pg_trgm`. It is idempotent
   against every existing database, which already has all three. The Docker init script and
   entrypoint stay: they are harmless and cover databases created before the migration. After
   this, `alembic upgrade head` against an empty Postgres with pgvector installed is a complete
   setup.

6. **One entry point for a native server:** `python -m app.serve`. It runs `alembic upgrade head`,
   then starts uvicorn with one worker, which is what `docker/entrypoint.sh` and the Dockerfile's
   `CMD` do. Host and port come from arguments; the default host is ADR-0134's. It does not install,
   locate or start Postgres; that is the packager's job.

7. **External programs are found on `PATH`, and the packager puts them there.** The bare `ffmpeg`
   and `ffprobe` calls stay. A native distribution prepends its own `bin/` to the server's `PATH`.
   `yt-dlp`, which updates itself at every container start (`docker/entrypoint.sh`), is not part of
   a native distribution. Music videos are absent there, not broken, following the ADR-0116 pattern
   of withholding what is not configured.

8. **The CLAP artifacts become a release output, pinned by hash.** The release workflow already
   builds the export stage. It additionally publishes `clap_audio.onnx`, `clap_text.onnx` (and its
   `.data`) and `tokenizer.json` as release assets, and records their SHA-256 in the backend. A
   native server looks for them under `data_dir/models/clapback` and, if they are missing,
   downloads them from the release matching its own version and refuses any file whose hash
   differs. This keeps the Dockerfile's premise: the files are produced by the pinned export and
   verified, not trusted from a URL. They are no longer produced on the machine that runs them.
   Until the download finishes, the server runs as it does with `DISABLE_CLAP_EMBEDDINGS`.

## Alternatives Considered

- **Port to SQLite (with sqlite-vec) so the native server needs no database server.** This would
  remove the heaviest thing to package. Rejected on the count in Context: the pgvector, trigram,
  upsert, raw-SQL and migration surface would all need rewriting, and every test would then prove
  SQLite while the NAS runs Postgres. ADR-0128 records the same judgement for tests.
- **Ship Docker in disguise: a bundled Colima or Podman VM behind an app icon.** This changes no
  server code, and the Docker path is already proven. Rejected because it keeps the part that makes
  the install heavy (a Linux VM, a multi-GB image, the RAM a VM holds) and hides it where a user
  cannot debug it. It also puts a hypervisor in the background of someone's laptop, which is the opposite of
  ADR-0137's etiquette.
- **Leave the relative `data/` paths and have the packager `chdir` into the data directory.** It
  works with no code change. Rejected because correctness would then depend on the process's
  working directory, which nothing checks: one packager forgetting to `chdir` writes settings into
  the app bundle, or fails in a sandbox. There are thirteen sites today, and a lint is cheap.
- **Bundle the CLAP artifacts in every native package instead of downloading them.** This works
  offline from the first launch. Not rejected outright; it is left to the packager. ADR-0136 may
  bundle them. The server-side decision is only that a missing artifact is fetched and verified
  rather than exported.

## Consequences

- **Positive:** `alembic upgrade head` plus `python -m app.serve` against any Postgres with pgvector
  is a complete server. This is also a faster development loop than today's compose stack.
- **Positive:** the zero-touch check can become the refusal `docs/ZERO-TOUCH.md` specified. Today
  it is a warning in `validate_library_path` (`app/main.py`) that tests by writing a temporary file
  into the library (ADR-0136 point 5).
- **Tradeoff:** there are now two runtimes to keep working. The Docker smoke test covers one; CI
  needs a job that runs the backend suite on macOS without the image.
- **Tradeoff:** the release pipeline gains about 614 MB of assets per version and a hash table that
  has to change whenever `clapback-embed`'s pinned checkpoint does.
- **Follow-up:** `docs/MACOS.md`'s development setup can drop Docker once ADR-0133 lands.
