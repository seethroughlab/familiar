# Plan: Split Docker Image into API + Worker Services

## Context

The current Familiar Docker image is >2GB because it bundles everything — FastAPI API server, audio analysis dependencies (PyTorch ~200MB CPU, librosa, transformers/CLAP ~500MB, etc.), and frontend assets — into a single monolith. The goal is to split this into a lightweight API image (~400-500MB) and a heavy Worker image (~2GB+) so that:

1. The API container restarts fast and uses minimal RAM (~500MB vs ~6GB)
2. Worker can be scaled or deployed independently
3. Systems that don't need analysis can skip the worker entirely

The codebase is already well-prepared for this — heavy imports are isolated to `analysis.py` (with lazy/conditional loading), analysis runs in subprocess via `ProcessPoolExecutor`, and Redis is already used for progress reporting. The main gap is: task dispatching is in-memory (no persistent queue), so we need a Redis-based task queue for cross-service communication.

### Current State (already done)

- **Multi-stage Dockerfile** already exists (4 stages: frontend builder → python-base → python-deps → production)
- **CPU-only PyTorch** already installed separately (`--index-url .../cpu`, ~200MB vs ~5GB CUDA)
- **Analysis deps already separated** in `pyproject.toml` as `[project.optional-dependencies] analysis = [...]`
- **Heavy imports already isolated**: `analysis.py` uses conditional torch, lazy transformers/CLAP, lazy pyloudnorm; `embedding_map.py` uses lazy umap/sklearn
- **Redis already used** for sync progress, distributed lock, and task failure tracking
- **Analysis runs in subprocess** via `ProcessPoolExecutor` with spawn context (1 worker)

### What's missing

- No persistent task queue — dispatching is in-memory via `BackgroundManager`
- No separate worker entry point — everything runs inside the uvicorn process
- No API-only Docker image — single image includes all deps
- No `SERVICE_ROLE` concept — can't run API without analysis deps installed

## Critical Files

| File | Role |
|------|------|
| `backend/app/config.py` | Add `SERVICE_ROLE` setting |
| `backend/app/services/background.py` | Modify to dispatch via Redis queue in split mode |
| `backend/app/services/tasks.py` | Contains `run_library_sync`, `queue_tracks_for_features/embeddings` — the worker calls these directly |
| `backend/app/main.py` | Conditional startup based on service role |
| `backend/pyproject.toml` | Add `api` optional dependency group |
| `backend/app/services/redis_client.py` | Existing `ResilientRedisClient` — reuse for task queue |
| `docker/Dockerfile` | Existing monolith (keep unchanged, add `SERVICE_ROLE=all`) |
| `docker/entrypoint.sh` | Guard yt-dlp update for worker |
| `.github/workflows/release.yml` | Build/push additional images |
| `.github/workflows/ci.yml` | Build-test new Dockerfiles |

## Implementation

### Step 1: Add `SERVICE_ROLE` to config

**File:** `backend/app/config.py`

Add to `Settings` class (after existing fields, before `@property sync_database_url`):

```python
# Service role: "all" (monolith), "api" (no analysis), "worker" (analysis only)
service_role: str = "all"

@property
def is_api(self) -> bool:
    return self.service_role in ("all", "api")

@property
def is_worker(self) -> bool:
    return self.service_role in ("all", "worker")

@property
def is_monolith(self) -> bool:
    return self.service_role == "all"
```

Default `"all"` = zero behavior change until explicitly overridden via `SERVICE_ROLE` env var.

### Step 2: Add `api` dependency group to pyproject.toml

**File:** `backend/pyproject.toml`

Add new optional group after existing `analysis` group:

```toml
# Lightweight deps for API-only deployment (no torch/librosa/transformers)
api = [
    "numpy>=1.24.0",          # embedding_map, ego_map, community_cache
    "scikit-learn>=1.3.0",     # ego_map cosine_similarity (top-level import)
    "umap-learn>=0.5.0",       # music map visualization (lazy import in embedding_map)
]
```

These are needed by the API for map visualization and similarity endpoints. Everything else (torch, librosa, transformers, soundfile, pyloudnorm) stays in `analysis` only.

Also add `scikit-learn>=1.3.0` explicitly to the `analysis` group (currently only transitive via umap-learn).

Run `cd backend && uv lock` to regenerate lockfile.

### Step 3: Create Redis task queue module

**New file:** `backend/app/services/task_queue.py`

Simple Redis-based queue using LPUSH/BRPOP pattern (no Celery needed):

- **Queue keys:** `familiar:tasks:sync`, `familiar:tasks:features`, `familiar:tasks:embedding`
- **Heartbeat key:** `familiar:worker:heartbeat` (TTL 60s, updated every 15s)

**TaskQueue class** (used by API to dispatch work):
```python
class TaskQueue:
    """Enqueue tasks for worker consumption. Used when SERVICE_ROLE=api."""

    def __init__(self, redis: ResilientRedisClient):
        self.redis = redis

    def enqueue_analysis(self, track_id: str, phase: str) -> None:
        queue = FEATURES_QUEUE if phase == "features" else EMBEDDING_QUEUE
        self.redis.client.lpush(queue, json.dumps({
            "track_id": track_id, "phase": phase,
            "queued_at": datetime.utcnow().isoformat()
        }))

    def enqueue_sync(self, reread_unchanged: bool = False) -> None:
        self.redis.client.lpush(SYNC_QUEUE, json.dumps({
            "reread_unchanged": reread_unchanged,
            "queued_at": datetime.utcnow().isoformat()
        }))
```

**TaskConsumer class** (runs in Worker process):
```python
class TaskConsumer:
    """Consume tasks from Redis queues. Runs in worker process."""

    async def run_forever(self):
        """Main loop: BRPOP from queues, execute, report progress."""
        while self._running:
            # BRPOP with 5s timeout, priority order: sync > features > embedding
            result = await asyncio.to_thread(
                self.redis.client.brpop,
                [SYNC_QUEUE, FEATURES_QUEUE, EMBEDDING_QUEUE],
                timeout=5,
            )
            if result is None:
                continue
            queue_name, task_data = result
            await self._execute_task(queue_name, json.loads(task_data))
```

The consumer calls `run_track_features`, `run_track_embedding` (from `tasks.py`) via the existing `BackgroundManager.run_cpu_bound()` for subprocess isolation, and `run_library_sync` for sync tasks. Same execution path as monolith — only the dispatch mechanism changes.

Worker heartbeat runs in a background asyncio task, updating Redis every 15s.

### Step 4: Modify BackgroundManager for dispatch mode

**File:** `backend/app/services/background.py`

**4a.** Add lazy `TaskQueue` property:

```python
@property
def task_queue(self) -> TaskQueue:
    if self._task_queue is None:
        from app.services.task_queue import TaskQueue
        self._task_queue = TaskQueue(self.redis)
    return self._task_queue
```

**4b.** Modify `run_analysis()` (currently at line ~600):

```python
async def run_analysis(self, track_id: str, phase: str = "full") -> dict:
    if not settings.is_worker:
        # API-only mode: dispatch to Redis queue
        if phase == "full":
            self.task_queue.enqueue_analysis(track_id, "features")
            # Embedding will be queued by sync loop after features complete
        else:
            self.task_queue.enqueue_analysis(track_id, phase)
        return {"status": "queued"}

    # Monolith or worker mode: existing in-process behavior (unchanged)
    task_key = f"{track_id}:{phase}"
    # ... rest of existing code ...
```

**4c.** Modify `run_sync()` (currently at line ~959):

```python
async def run_sync(self, reread_unchanged: bool = False) -> dict:
    if not settings.is_worker:
        # API-only mode: dispatch to Redis queue
        if self.is_sync_running():
            return {"status": "already_running"}
        self.task_queue.enqueue_sync(reread_unchanged)
        return {"status": "started"}

    # Monolith or worker mode: existing in-process behavior (unchanged)
    # ... rest of existing code ...
```

**4d.** Skip ProcessPoolExecutor creation in API mode. In `executor` property:

```python
@property
def executor(self) -> ProcessPoolExecutor:
    if not settings.is_worker:
        raise RuntimeError("ProcessPoolExecutor not available in API-only mode")
    if self._executor is None:
        self._create_executor()
    return self._executor
```

**4e.** In `startup()`: skip worker health check scheduler job when `SERVICE_ROLE=api`.

### Step 5: Conditional startup in main.py

**File:** `backend/app/main.py`

In the `lifespan()` function (line ~129):

```python
# Only check analysis capabilities in monolith mode (imports from analysis.py)
if settings.is_monolith:
    from app.services.analysis import check_analysis_capabilities
    check_analysis_capabilities()

# Start background task manager (scheduler, artwork fetcher)
from app.services.background import get_background_manager
bg = get_background_manager()
await bg.startup()
```

API mode: scheduler starts (enqueues periodic sync/new-releases to Redis), artwork fetcher starts, but no analysis capability check.
Monolith mode: unchanged.

### Step 6: Create worker entry point

**New file:** `backend/app/worker.py`

```python
"""Standalone worker for Familiar audio analysis.

Consumes tasks from Redis queues, runs analysis in subprocesses.
Usage: python -m app.worker
"""
```

The worker:
1. Sets `SERVICE_ROLE=worker` default via `os.environ.setdefault`
2. Forces `multiprocessing.set_start_method("spawn")`
3. Creates a `BackgroundManager` (which creates the `ProcessPoolExecutor`)
4. Instantiates `TaskConsumer` and runs its loop
5. Runs heartbeat update concurrently via `asyncio.create_task`
6. Handles SIGINT/SIGTERM for graceful shutdown (cancel consumer, shutdown executor)

The worker does NOT start uvicorn, FastAPI, APScheduler, or the artwork fetcher. It only processes tasks from Redis queues.

### Step 7: Update health endpoint for split mode

**File:** `backend/app/api/routes/health.py`

In `system_health_check()` (line ~177) and `get_worker_status()` (line ~312):

When `settings.is_monolith` is False, check worker status via Redis heartbeat instead of inspecting in-memory BackgroundManager:

```python
from app.config import settings
if settings.is_monolith:
    # Existing in-process check (unchanged)
    bg = get_background_manager()
    # ...
else:
    # Check worker heartbeat in Redis
    heartbeat_data = redis_client.get("familiar:worker:heartbeat")
    if heartbeat_data:
        hb = json.loads(heartbeat_data)
        # Healthy if heartbeat < 60s old
        services.append(ServiceStatus(name="worker", status="healthy", ...))
    else:
        services.append(ServiceStatus(name="worker", status="unhealthy",
                                       message="Worker not responding"))
```

### Step 8: Create Dockerfile.api

**New file:** `docker/Dockerfile.api`

Same 4-stage structure as existing `docker/Dockerfile`, with key differences:

**Stage 3 (deps):**
```dockerfile
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv && \
    uv sync --frozen --no-dev --extra api && \
    uv pip install 'yt-dlp[default]'
```

No `--extra analysis`, no `torch` install.

**Stage 4 (production):**
- Same runtime deps (libpq5, ffmpeg, gosu, libcurl4-openssl-dev, postgresql-client, curl, unzip, Deno)
- Same entrypoint.sh
- Same frontend static files
- Adds `ENV SERVICE_ROLE=api`
- Same CMD, healthcheck

### Step 9: Create Dockerfile.worker

**New file:** `docker/Dockerfile.worker`

Only 3 stages (no frontend build):

**Stage 2 (deps):**
```dockerfile
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv && \
    uv sync --frozen --no-dev --extra analysis && \
    uv pip install torch --index-url https://download.pytorch.org/whl/cpu
```

**Stage 3 (production):**
- Minimal runtime deps: `libpq5`, `ffmpeg`, `gosu` only
- No Deno, no yt-dlp, no postgresql-client, no libcurl4-openssl-dev
- No frontend static files
- Uses `docker/entrypoint-worker.sh`
- `ENV SERVICE_ROLE=worker`
- `CMD ["python", "-m", "app.worker"]`
- Healthcheck: `python -c "import redis,os; r=redis.from_url(os.environ['REDIS_URL']); assert r.get('familiar:worker:heartbeat')"`

### Step 10: Create worker entrypoint

**New file:** `docker/entrypoint-worker.sh`

Minimal — no yt-dlp update, no database migrations (API handles those):

```bash
#!/bin/bash
set -e
chown -R familiar:familiar /data/art 2>/dev/null || true
exec gosu familiar "$@"
```

### Step 11: Update existing Dockerfile (monolith)

**File:** `docker/Dockerfile`

Add one env var (line ~115, with the other ENV declarations):

```dockerfile
ENV SERVICE_ROLE=all
```

No other changes. Full backwards compatibility.

### Step 12: Update entrypoint.sh

**File:** `docker/entrypoint.sh`

Guard yt-dlp update with command check (line 8):

```bash
# Auto-update yt-dlp (only if installed — not present in worker image)
if command -v yt-dlp &> /dev/null; then
    gosu familiar uv pip install -U 'yt-dlp[default]' -q || true
fi
```

### Step 13: Create docker-compose.split.yml

**New file:** `docker/docker-compose.split.yml`

Reference compose file demonstrating split deployment. Based on `docker-compose.prod.yml` structure:

```yaml
services:
  postgres:
    # ... same as prod ...
  redis:
    # ... same as prod ...
  api:
    image: ghcr.io/seethroughlab/familiar-api:${FAMILIAR_VERSION:-latest}
    container_name: familiar-api
    restart: unless-stopped
    ports:
      - "${API_PORT:-4400}:8000"
    deploy:
      resources:
        limits: { cpus: '1.0', memory: 1G }
    volumes:
      - ${MUSIC_LIBRARY_PATH}:/music:rw
      - app_data:/app/data
      - art_data:/data/art
      - videos_data:/data/videos
    environment:
      - DATABASE_URL=postgresql+asyncpg://familiar:${POSTGRES_PASSWORD:-familiar}@postgres:5432/familiar
      - REDIS_URL=redis://redis:6379/0
      - SERVICE_ROLE=api
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
  worker:
    image: ghcr.io/seethroughlab/familiar-worker:${FAMILIAR_VERSION:-latest}
    container_name: familiar-worker
    restart: unless-stopped
    deploy:
      resources:
        limits: { cpus: '2.0', memory: 6G }
        reservations: { memory: 512M }
    volumes:
      - ${MUSIC_LIBRARY_PATH}:/music:ro
      - art_data:/data/art
    environment:
      - DATABASE_URL=postgresql+asyncpg://familiar:${POSTGRES_PASSWORD:-familiar}@postgres:5432/familiar
      - REDIS_URL=redis://redis:6379/0
      - SERVICE_ROLE=worker
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
```

### Step 14: Update CI/CD

**File:** `.github/workflows/release.yml`

After existing monolith build step, add two more build-and-push steps:

```yaml
- name: Build and push API image
  uses: docker/build-push-action@v6
  with:
    context: .
    file: docker/Dockerfile.api
    push: true
    tags: ghcr.io/seethroughlab/familiar-api:${{ steps.version.outputs.version }},ghcr.io/seethroughlab/familiar-api:latest
    build-args: VERSION=${{ steps.version.outputs.version }}
    cache-from: type=gha
    cache-to: type=gha,mode=max

- name: Build and push Worker image
  uses: docker/build-push-action@v6
  with:
    context: .
    file: docker/Dockerfile.worker
    push: true
    tags: ghcr.io/seethroughlab/familiar-worker:${{ steps.version.outputs.version }},ghcr.io/seethroughlab/familiar-worker:latest
    build-args: VERSION=${{ steps.version.outputs.version }}
    cache-from: type=gha
    cache-to: type=gha,mode=max
```

**File:** `.github/workflows/ci.yml`

In the `docker-build` job, add build-only (no push) steps for `Dockerfile.api` and `Dockerfile.worker`.

## Expected Image Sizes

| Image | Size | RAM (typical) |
|-------|------|---------------|
| Monolith (`familiar`) | ~2.5GB (unchanged) | ~4-6GB |
| API (`familiar-api`) | ~400-500MB | ~300-500MB |
| Worker (`familiar-worker`) | ~2.2GB | ~2-4GB |

API savings come from removing: PyTorch CPU (~200MB), librosa+deps (~100MB), transformers+tokenizers (~500MB). It's larger than ~200MB because ffmpeg (~80MB), Deno (~40MB), anthropic, boto3, and other core deps still add up.

## Verification

1. **Monolith still works:** `SERVICE_ROLE=all` (default) — run existing Docker image, confirm sync + analysis work as before
2. **API-only starts cleanly:** `SERVICE_ROLE=api` — confirm FastAPI starts without importing torch/librosa, scheduler enqueues to Redis
3. **Worker processes tasks:** `SERVICE_ROLE=worker` — confirm worker picks up tasks from Redis queues and runs analysis in subprocess
4. **Split deployment E2E:** Run `docker-compose.split.yml`, trigger sync from API, verify worker processes analysis and reports progress via Redis
5. **Image sizes:** Compare `docker images` output — API should be <500MB
6. **Health endpoint:** `/api/v1/health/system` reports worker status via Redis heartbeat in split mode
7. **Existing tests pass:** `cd backend && make test` — all tests pass (monolith mode, `SERVICE_ROLE=all`)
