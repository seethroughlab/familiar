FROM node:20-alpine AS frontend-builder

RUN corepack enable && corepack prepare pnpm@latest --activate

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
