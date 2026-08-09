# **Match `docker/Dockerfile` exactly.** These two build definitions drifted, and the demo build
# broke on 2026-08-09 because of it: `pnpm@latest` resolved to 11.21.0, which requires Node ≥22.13
# and imports `node:sqlite`, a module Node 20 does not have. The release image had been on
# `node:22-alpine` with `pnpm@10` — pinned — the whole time.
#
# **`pnpm@latest` in a Dockerfile is the actual defect.** It makes the build non-reproducible: the
# same commit built successfully last month and fails today because a package manager released a
# major version. Pinned here for the same reason the release image pins.
#
# ADR-0038's follow-up asks whether the demo should build from the same image the release publishes.
# Until that is answered, these two files have to be kept in step by hand, and this is what happens
# when they are not.
FROM node:22-alpine AS frontend-builder

RUN corepack enable && corepack prepare pnpm@10 --activate

WORKDIR /app

ENV NPM_CONFIG_FETCH_RETRIES=5 \
    NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=120000 \
    NPM_CONFIG_FETCH_TIMEOUT=600000

COPY pnpm-workspace.yaml package.json pnpm-lock.yaml ./
COPY packages/frontend/package.json packages/frontend/
COPY packages/web/package.json packages/web/

RUN pnpm install --frozen-lockfile --filter @familiar/web...

COPY packages/frontend/ packages/frontend/
COPY packages/web/ packages/web/
RUN pnpm --filter @familiar/web run build

FROM python:3.11-slim AS python-base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=120

WORKDIR /app

FROM python-base AS deps

COPY backend/pyproject.toml backend/uv.lock backend/README.md ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv && \
    uv sync --frozen --no-dev

FROM python-base AS prod

ARG VERSION=demo
RUN echo "${VERSION}" > /app/VERSION

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    ffmpeg \
    gosu \
    libcurl4-openssl-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY --from=deps /app/.venv /app/.venv

COPY backend/app ./app
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations

COPY --from=frontend-builder /app/packages/web/dist ./static

RUN useradd --create-home --shell /bin/bash familiar \
    && mkdir -p /data/music /data/art /data/videos /app/data \
    && chown -R familiar:familiar /app /data

COPY deploy/fly/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

ENV PATH="/app/.venv/bin:$PATH" \
    MUSIC_LIBRARY_PATH=/data/music \
    ART_PATH=/data/art \
    VIDEOS_PATH=/data/videos \
    DISABLE_CLAP_EMBEDDINGS=true

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/api/v1/health', timeout=5)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
