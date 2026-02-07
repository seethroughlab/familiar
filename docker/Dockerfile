# Multi-stage Dockerfile for Familiar
# Builds both frontend and backend into a single production image

# =============================================================================
# Stage 1: Build frontend
# =============================================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# Copy package files
COPY frontend/package*.json ./

# Install dependencies
RUN npm ci

# Copy source and build
COPY frontend/ ./
RUN npm run build

# =============================================================================
# Stage 2: Python base with uv
# =============================================================================
FROM python:3.11-slim AS python-base

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# =============================================================================
# Stage 3: Install Python dependencies
# =============================================================================
FROM python-base AS python-deps

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
    uv pip install yt-dlp

# =============================================================================
# Stage 4: Production image
# =============================================================================
FROM python-base AS production

# Version injected at build time (from git tag)
ARG VERSION=dev
RUN echo "${VERSION}" > /app/VERSION

# Install runtime dependencies
# libcurl4-openssl-dev is required for curl_cffi (TLS fingerprint impersonation)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    ffmpeg \
    gosu \
    libcurl4-openssl-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy Python virtual environment from deps stage
COPY --from=python-deps /app/.venv /app/.venv

# Copy backend application code
COPY backend/app ./app

# Copy Alembic configuration
# Note: migrations/ instead of alembic/ to avoid shadowing the alembic package
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations

# Copy built frontend
COPY --from=frontend-builder /app/frontend/dist ./static

# Create non-root user and directories
RUN useradd --create-home --shell /bin/bash familiar \
    && mkdir -p /data/music /data/art /data/videos /app/data \
    && chown -R familiar:familiar /app /data

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
    VIDEOS_PATH=/data/videos

# Expose API port
EXPOSE 8000

# Health check for API (worker overrides this in docker-compose)
HEALTHCHECK --interval=30s --timeout=30s --start-period=30s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/api/v1/health', timeout=20)" || exit 1

# Default command runs the API server with a single worker
# Single worker is required because each worker spawns its own analysis subprocess
# with CLAP model (~1.5GB RAM). Multiple workers would cause OOM on resource-limited systems.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
