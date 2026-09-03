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
# Pinned to the patch, and **must stay equal to `UV_PYTHON` in `.github/workflows/ci.yml`** — that
# is what makes CI test the interpreter this image ships. `3.11-slim` floated, so the two could
# drift a patch apart without either file changing; on 2026-08-22 a single patch release was enough
# to flip two tests, so a floating tag is not close enough. Bump both together.
FROM python:3.11.15-slim AS python-base

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
# git is needed by uv to resolve `clapback-embed @ git+...`, which is published
# from the clapback repository and not yet on an index. This is a builder
# stage, so git does not reach the production image — and if the package ever
# ships to PyPI, this line goes with the git dependency.
RUN apt-get update && apt-get install -y --no-install-recommends g++ git && rm -rf /var/lib/apt/lists/*

# Copy only dependency files first for caching
COPY backend/pyproject.toml ./
COPY backend/uv.lock ./
COPY backend/README.md ./

# Install dependencies (without dev extras for production, with analysis extras)
# Install CPU-only PyTorch AFTER uv sync (~200MB vs ~5GB for CUDA version)
# Install yt-dlp for YouTube video downloads
# Note: uv sync removes packages not in lockfile, so these must come last
# CUDA userspace for the GPU path. Pinned hard, because every mismatched
# combination **silently falls back to CPU and reports success** — ONNX Runtime
# logs a warning and carries on, so a broken GPU build looks exactly like a
# working one. Four combinations were tried before this one ran; see ADR-0105.
#
#   onnxruntime-gpu 1.18.1  is the last wheel built against CUDA 11
#   nvidia-cudnn-cu11       MUST be pinned to 8.x — the unpinned wheel now ships
#                           cuDNN 9, which 1.18.1 cannot load
#   driver 535 caps at CUDA 12.2, and ORT >=1.19 wants CUDA 12 + cuDNN 9, so
#   CUDA 11.8 is the only rung where both ends meet on the deployment host.
#
# Harmless without a GPU: the provider fails to initialise and CPU is used, which
# is the same outcome as not installing it.
#
# x86_64 only: onnxruntime-gpu publishes no aarch64 wheels (manylinux_*_x86_64 and
# win_amd64 only), and CUDA is not reachable on the arm64 builds regardless. On
# aarch64 the CPU `onnxruntime` that clapback-embed depends on is left in place,
# which is the same outcome as before this change.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv && \
    uv sync --frozen --no-dev --extra analysis && \
    if [ "$(uname -m)" = "x86_64" ]; then \
        uv pip install \
            'onnxruntime-gpu==1.18.1' \
            'nvidia-cudnn-cu11==8.9.6.50' \
            nvidia-cublas-cu11 nvidia-cuda-runtime-cu11 \
            nvidia-cufft-cu11 nvidia-curand-cu11; \
    else \
        echo "aarch64: skipping CUDA runtime, embedder will use CPU"; \
    fi && \
    uv pip install 'yt-dlp[default]'

# =============================================================================
# Stage 3b: Export the ONNX encoders
# =============================================================================
# The artifacts are 112 MB (audio) and 502 MB (text) and are generated here rather
# than vendored or downloaded. torch and transformers are needed to export them and
# are needed by nothing at runtime, so they live in a stage the final image does not
# copy from — which is how the runtime stays ONNX-only while the artifacts stay
# reproducible from the pinned checkpoint rather than trusted from a URL.
#
# `export_models.py` verifies every export against PyTorch before writing. An
# artifact that disagrees is worse than a missing one: it yields plausible vectors
# that are comparable with nothing.
#
# transformers is bounded here even though the runtime no longer depends on it at
# all. The artifacts *are* the contract, so the thing that produces them cannot
# float: an unpinned range already broke this stage once, when `processor(audios=)`
# was deprecated out from under it. `<5` because 5.x changes `get_text_features`
# to return an object rather than a tensor — the export wrapper handles both, but
# the boundary is a real one and should be crossed deliberately.
FROM python-base AS onnx-export
WORKDIR /export
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /opt/exportenv && \
    VIRTUAL_ENV=/opt/exportenv uv pip install \
        torch --index-url https://download.pytorch.org/whl/cpu && \
    VIRTUAL_ENV=/opt/exportenv uv pip install \
        'transformers>=4.40,<5' onnx onnxruntime numpy
# Fetched rather than COPY --from: `scripts/` is not part of the wheel, so it does
# not exist in the installed package. Same mechanism the image already uses for
# silero_vad.onnx below.
ADD https://raw.githubusercontent.com/seethroughlab/clapback/main/packages/embed/scripts/export_models.py ./export_models.py
RUN --mount=type=cache,target=/root/.cache/huggingface \
    /opt/exportenv/bin/python export_models.py --out /models

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
#
# This lands under /app/data, which is a named volume in production. It works
# only because the volume was first created by an image that already contained
# it — named volumes copy the image's contents in once, at creation, and never
# again. **Replacing this file in the image would not reach any existing
# installation**, silently. The CLAP encoders hit exactly that and now live in
# /app/models instead; this one is left where it is because moving it would
# strand the copy already in every deployed volume, but it should move the next
# time silero is updated for any other reason.
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
# The ONNX encoders, generated in stage 3b.
#
# **Deliberately NOT under /app/data.** That path is a named volume in
# docker-compose.prod.yml (app_data, which persists settings.json), and a named
# volume only initialises from the image the first time it is created. On any
# existing installation the volume predates these files, so shipping them to
# /app/data/models would put them in the image and hide them from the container —
# which is exactly what happened: the release smoke test passed under `docker run`
# with no volumes and the same image failed on the NAS with "clap_audio.onnx not
# found". The stale silero_vad.onnx sitting in that volume is the fossil of the
# same mechanism working once, years ago.
#
# --chown here for the same reason the COPYs above use it: a recursive chown over
# /app took 9m12s of a 17m30s build.
COPY --from=onnx-export --chown=familiar:familiar /models /app/models/clapback

RUN mkdir -p /data/music /data/art /data/videos /data/mixtapes /app/data \
    && chown familiar:familiar /app /app/VERSION \
    && chown -R familiar:familiar /data /app/data

# Copy entrypoint script
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

# Ensure the virtual environment is in PATH
ENV PATH="/app/.venv/bin:$PATH"

# Where clapback-embed finds the encoders copied in from the export stage.
# /app/models, not /app/data/models — see the COPY above for why that matters.
ENV CLAPBACK_MODEL_DIR=/app/models/clapback

# The CUDA libraries arrive as pip packages under site-packages/nvidia/*/lib, which
# the dynamic linker does not search on its own. Without this the CUDA provider
# fails to load and ONNX Runtime **silently uses the CPU** — the failure mode that
# cost four attempts in ADR-0105.
ENV LD_LIBRARY_PATH="/app/.venv/lib/python3.11/site-packages/nvidia/cudnn/lib:/app/.venv/lib/python3.11/site-packages/nvidia/cublas/lib:/app/.venv/lib/python3.11/site-packages/nvidia/cuda_runtime/lib:/app/.venv/lib/python3.11/site-packages/nvidia/cufft/lib:/app/.venv/lib/python3.11/site-packages/nvidia/curand/lib"

# Ask for the GPU, fall back to CPU. Both are corpus-safe: CUDA and CPU vectors
# agree to 6.6e-14, against the 6.0e-08 that float4 storage already costs
# (measured on a GTX 980, ADR-0105). Unlike fp16, this is not a precision tradeoff.
ENV CLAPBACK_PROVIDERS="CUDAExecutionProvider,CPUExecutionProvider"

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
