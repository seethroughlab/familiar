# Deploy Familiar Test Server to Fly.io

## Context

Apple App Store review requires a working backend server with test data. A fly.io test server also enables CI/E2E testing against a real environment. The server will host a small library of CC-licensed music, pre-analyzed and ready for reviewers to use.

## Architecture

- Full-stack deploy using existing `docker/Dockerfile` (single container: FastAPI + React frontend)
- Fly Postgres (pgvector included in Fly Postgres 15+)
- Upstash Redis (Fly's recommended Redis, free tier sufficient)
- Single persistent volume at `/data` for music, art, settings
- Always-on `performance-2x` VM (4 CPU, 8GB RAM) — ~$55/month total
- Region: `sjc` (San Jose, near Apple in Cupertino)

## Files to Create

### 1. `fly.toml` (repo root)

Fly.io app configuration:
- App name: `familiar-test`
- Build from `docker/Dockerfile`
- Mount volume `familiar_data` at `/data`
- Env: `MUSIC_LIBRARY_PATH=/data/music`, `ART_PATH=/data/art`, `VIDEOS_PATH=/data/videos`
- Health check: `GET /api/v1/health` every 30s, 60s grace period
- `auto_stop_machines = "off"`, `min_machines_running = 1` (always-on)
- VM: `performance-2x` with 8GB RAM

### 2. `fly/seed-music.sh`

Script to download CC-licensed music and trigger library scan:
- Downloads tracks from incompetech.com (Kevin MacLeod, CC-BY 4.0) and archive.org (public domain classical)
- Places files in `/data/music/` organized by artist folder
- Triggers library scan via `POST http://localhost:8000/api/v1/sync`
- Run via: `fly ssh console -C "bash /app/fly/seed-music.sh"`

### 3. `.github/workflows/deploy-fly.yml`

GitHub Actions workflow for deploying to Fly:
- Triggers: `workflow_dispatch` (manual) and on version tags (`v*`)
- Uses `superfly/flyctl-actions/setup-flyctl`
- Runs `flyctl deploy --remote-only`
- Requires `FLY_API_TOKEN` secret in GitHub

## Files to Modify

### 4. `docker/Dockerfile`

- Add `COPY fly/ ./fly/` after the backend copy step (to include seed script in image)

### 5. `docker/entrypoint.sh`

Add Fly.io detection using `FLY_APP_NAME` env var (always set on Fly machines):
- **Skip `gosu`**: Fly runs in single-tenant microVMs, root is fine
- **Volume setup**: `mkdir -p /data/music /data/art /data/videos /data/app_data`
- **Symlink settings**: `ln -sf /data/app_data /app/data` so `settings.json` survives redeploys
- **Add missing extensions**: The current entrypoint only creates the `vector` extension. Add `uuid-ossp` and `pg_trgm` (needed by the app, currently created by the Docker Postgres init script but not available on Fly Postgres)

Implementation approach — add at the top of `entrypoint.sh`:
```bash
if [ -n "$FLY_APP_NAME" ]; then
    mkdir -p /data/music /data/art /data/videos /data/app_data
    [ ! -L /app/data ] && rm -rf /app/data && ln -sf /data/app_data /app/data
    RUN_AS=""
else
    chown -R familiar:familiar /app/data /data/art /data/videos 2>/dev/null || true
    RUN_AS="gosu familiar"
fi
```
Then replace all `gosu familiar` with `$RUN_AS`.

In the extensions block, add `uuid-ossp` and `pg_trgm` alongside `vector`.

## Infrastructure Setup Sequence (manual, one-time)

```bash
# 1. Create app
fly apps create familiar-test

# 2. Create Postgres (pgvector included)
fly postgres create --name familiar-test-db --region sjc \
  --vm-size shared-cpu-1x --initial-cluster-size 1 --volume-size 1

# 3. Attach Postgres (auto-sets DATABASE_URL secret)
fly postgres attach familiar-test-db -a familiar-test
# Then override with asyncpg driver prefix:
fly secrets set DATABASE_URL="postgresql+asyncpg://..." -a familiar-test

# 4. Create Upstash Redis
fly redis create --name familiar-test-redis --region sjc
fly secrets set REDIS_URL="redis://..." -a familiar-test

# 5. Create persistent volume (3GB)
fly volumes create familiar_data --size 3 --region sjc -a familiar-test

# 6. Set secrets
fly secrets set ANTHROPIC_API_KEY="..." FRONTEND_URL="https://familiar-test.fly.dev" -a familiar-test

# 7. Deploy
fly deploy --remote-only

# 8. Seed test music
fly ssh console -C "bash /app/fly/seed-music.sh" -a familiar-test
```

## Known Issues & Mitigations

| Issue | Mitigation |
|-------|-----------|
| `DATABASE_URL` format — Fly sets `postgres://`, app needs `postgresql+asyncpg://` | Manually override secret after `fly postgres attach` |
| DB pool size (40 total) may exceed Fly Postgres shared plan limits (~25 connections) | Single worker + test usage = fine; reduce pool if issues arise |
| CC music download URLs may break over time | Seed script uses multiple sources; can also manually upload files to the volume |
| Large Docker image (~4-6GB) | Use `--remote-only` to build on Fly's builders with layer caching |

## Verification

1. `fly status -a familiar-test` — machine running, health checks passing
2. `curl https://familiar-test.fly.dev/api/v1/health` — 200 OK
3. Open `https://familiar-test.fly.dev` in browser — app loads, test tracks visible
4. Play a track — audio streams correctly
5. Test from iOS app — point at `https://familiar-test.fly.dev`, verify playback
