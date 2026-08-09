# Multi-stage Dockerfile for Familiar
# Builds both frontend and backend into a single production image

# =============================================================================
# Stage 1: Build frontend (pnpm workspace)
# =============================================================================
FROM node:22-alpine AS frontend-builder

RUN corepack enable && corepack prepare pnpm@10 --activate

WORKDIR /app

# Harden npm registry fetches against slow/flaky networks (self-hosted CI
# has seen ETIMEDOUT downloading tarballs). Defaults: retries=2,
# fetch-timeout=60s, fetch-retry-maxtimeout=60s.
ENV NPM_CONFIG_FETCH_RETRIES=5 \
    NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=120000 \
    NPM_CONFIG_FETCH_TIMEOUT=600000

# Copy workspace config and package files for dependency caching
COPY pnpm-workspace.yaml package.json pnpm-lock.yaml ./
COPY packages/frontend/package.json packages/frontend/
COPY packages/web/package.json packages/web/

# Install dependencies (only what @familiar/web needs)
RUN pnpm install --frozen-lockfile --filter @familiar/web...

# Copy source and build.
# There is no sessions relay build argument. Listening sessions signal through the Familiar server
# this image *is* (ADR-0036); a build argument that silently sent listeners' session codes, chat and
# reactions to a third party was the thing that decision removed.
COPY packages/frontend/ packages/frontend/
COPY packages/web/ packages/web/
RUN pnpm --filter @familiar/web run build

# =============================================================================
# Stage 2: Python base with uv
# =============================================================================
FROM python:3.11-slim AS python-base

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set environment variables
# UV_HTTP_TIMEOUT raised from default 30s to survive slow PyPI fetches on
# self-hosted CI (safetensors/torch wheels are large and have timed out).
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=120

WORKDIR /app

# =============================================================================
# Stage 3: Install Python dependencies
# =============================================================================
FROM python-base AS python-deps

# g++ is needed to compile miniaudio (a pyatv dependency) which has no aarch64 wheel
RUN apt-get update && apt-get install -y --no-install-recommends g++ && rm -rf /var/lib/apt/lists/*

# Copy only dependency files first for caching
COPY backend/pyproject.toml ./
COPY backend/uv.lock ./
COPY backend/README.md ./

# Install dependencies (without dev extras for production, with analysis extras)
# Install CPU-only PyTorch AFTER uv sync (~200MB vs ~5GB for CUDA version)
# Install yt-dlp for YouTube video downloads
# Note: uv sync removes packages not in lockfile, so these must come last
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv && \
    uv sync --frozen --no-dev --extra analysis && \
    uv pip install torch --index-url https://download.pytorch.org/whl/cpu && \
    uv pip install 'yt-dlp[default]'

# =============================================================================
# Stage 4: Production image
# =============================================================================
FROM python-base AS production

# Version injected at build time (from git tag)
ARG VERSION=dev
RUN echo "${VERSION}" > /app/VERSION

# Install runtime dependencies
# libcurl4-openssl-dev is required for curl_cffi (TLS fingerprint impersonation)
# curl + unzip needed for Deno install
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    ffmpeg \
    gosu \
    libcurl4-openssl-dev \
    postgresql-client \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Deno - required by yt-dlp for YouTube JS challenge solving
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh

# Create the non-root user here rather than at the end, because every COPY
# below uses --chown and that needs the user to already exist. This ordering
# is what keeps the venv out of a recursive chown — see the note further down.
RUN useradd --create-home --shell /bin/bash familiar

# Copy Python virtual environment from deps stage
COPY --from=python-deps --chown=familiar:familiar /app/.venv /app/.venv

# Copy backend application code
COPY --chown=familiar:familiar backend/app ./app

# Copy smoke test script for post-build verification
COPY --chown=familiar:familiar backend/scripts/smoke_test_clap.py ./scripts/smoke_test_clap.py

# Copy Alembic configuration
# Note: migrations/ instead of alembic/ to avoid shadowing the alembic package
COPY --chown=familiar:familiar backend/alembic.ini ./
COPY --chown=familiar:familiar backend/migrations ./migrations

# Copy built frontend
COPY --from=frontend-builder --chown=familiar:familiar /app/packages/web/dist ./static

# Download silero-vad ONNX model (~2MB) for voice activity detection
RUN mkdir -p /app/data/models \
    && curl -fsSL -o /app/data/models/silero_vad.onnx \
       https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx

# Runtime data directories.
#
# The recursive chown here deliberately covers only /data (empty at build time)
# and /app/data (~2MB of models). Everything large under /app already arrived
# owned by familiar via COPY --chown above, which costs nothing because the
# ownership is set as the files are written.
#
# This step used to be `chown -R familiar:familiar /app /data`, and it took
# 9m12s of a 17m30s CI build on 2026-08-05 — /app/.venv is a CPU torch build
# with analysis extras, and walking it dominated the image. Do not reintroduce
# a recursive chown over /app; add --chown to the COPY instead.
RUN mkdir -p /data/music /data/art /data/videos /data/mixtapes /app/data \
    && chown familiar:familiar /app /app/VERSION \
    && chown -R familiar:familiar /data /app/data

# Copy entrypoint script
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

# Ensure the virtual environment is in PATH
ENV PATH="/app/.venv/bin:$PATH"

# Default environment variables
ENV DATABASE_URL=postgresql+asyncpg://familiar:familiar@postgres:5432/familiar \
    REDIS_URL=redis://redis:6379/0 \
    MUSIC_LIBRARY_PATH=/music \
    ART_PATH=/data/art \
    VIDEOS_PATH=/data/videos \
    MIXTAPES_PATH=/data/mixtapes

# Expose API port
EXPOSE 8000

# Health check for API (worker overrides this in docker-compose)
HEALTHCHECK --interval=30s --timeout=30s --start-period=30s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/api/v1/health', timeout=20)" || exit 1

# Default command runs the API server with a single worker
# Single worker is required because each worker spawns its own analysis subprocess
# with CLAP model (~1.5GB RAM). Multiple workers would cause OOM on resource-limited systems.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
