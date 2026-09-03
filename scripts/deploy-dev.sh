#!/bin/bash
# Quick deploy to NAS for development testing
# Builds frontend locally and rsyncs to NAS, then restarts container
# Usage: ./scripts/deploy-dev.sh [--backend-only] [--frontend-only]
set -e

NAS_HOST="${NAS_HOST:-openmediavault}"
REMOTE_PATH="/opt/familiar"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Parse arguments
DEPLOY_BACKEND=true
DEPLOY_FRONTEND=true

for arg in "$@"; do
    case $arg in
        --backend-only)
            DEPLOY_FRONTEND=false
            ;;
        --frontend-only)
            DEPLOY_BACKEND=false
            ;;
    esac
done

# Build frontend if needed
if [ "$DEPLOY_FRONTEND" = true ]; then
    echo "Building frontend..."
    pnpm --filter @familiar/web run build

    echo "Syncing frontend to $NAS_HOST..."
    rsync -avz --delete \
        --exclude 'node_modules' \
        --exclude '.git' \
        packages/web/dist/ jeff@$NAS_HOST:$REMOTE_PATH/frontend/dist/

fi

# Sync backend if needed
if [ "$DEPLOY_BACKEND" = true ]; then
    echo "Syncing backend to $NAS_HOST..."
    # Remove stale models.py if it exists alongside models/ package
    # Python prefers packages over modules — having both causes import confusion
    ssh jeff@$NAS_HOST "test -d $REMOTE_PATH/backend/app/db/models && rm -f $REMOTE_PATH/backend/app/db/models.py" 2>/dev/null || true
    rsync -avz \
        --exclude '__pycache__' \
        --exclude '.venv' \
        --exclude '*.pyc' \
        backend/app/ jeff@$NAS_HOST:$REMOTE_PATH/backend/app/

    echo "Syncing migrations to $NAS_HOST..."
    rsync -avz \
        --exclude '__pycache__' \
        --exclude '*.pyc' \
        backend/migrations/ jeff@$NAS_HOST:$REMOTE_PATH/backend/migrations/

    # scripts/ too. It was left out until 2026-08-12, when the ADR-0052 artwork
    # migration had to be `docker cp`-ed in by hand — the container was still carrying
    # whatever `scripts/` the image was built with, which is the sort of staleness that
    # only shows up when you finally need one of them.
    echo "Syncing scripts to $NAS_HOST..."
    rsync -avz \
        --exclude '__pycache__' \
        --exclude '*.pyc' \
        backend/scripts/ jeff@$NAS_HOST:$REMOTE_PATH/backend/scripts/
fi

echo "Restarting container..."
ssh jeff@$NAS_HOST "docker restart familiar-api"

# Install any packages not in the base image (temporary until image rebuild)
echo "Installing additional dependencies..."
ssh jeff@$NAS_HOST "docker exec familiar-api sh -c 'which pg_dump > /dev/null 2>&1 || apt-get update -qq && apt-get install -y -qq postgresql-client > /dev/null 2>&1'" || true
ssh jeff@$NAS_HOST "docker exec familiar-api sh -c 'which deno > /dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq curl unzip > /dev/null 2>&1 && curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh)'" || true
ssh jeff@$NAS_HOST "docker exec familiar-api uv pip install 'curl_cffi>=0.7.0' 'trafilatura>=1.6.0' 'boto3>=1.34.0' 'yt-dlp[default]' 'bcrypt>=4.0.0' 'pyloudnorm>=0.1.0' 'soundfile>=0.12.0' 'basic-pitch[onnx]>=0.3.0' 'matplotlib>=3.5.0' 'async-upnp-client>=0.47.0' 'mcp>=2.0.0' --python /app/.venv/bin/python -q" || true

# Copy code into container (container runs from /app/, not host filesystem)
if [ "$DEPLOY_BACKEND" = true ]; then
    echo "Copying backend into container..."
    ssh jeff@$NAS_HOST "docker cp $REMOTE_PATH/backend/app/. familiar-api:/app/app/"
fi

if [ "$DEPLOY_FRONTEND" = true ]; then
    echo "Copying frontend into container..."
    ssh jeff@$NAS_HOST "docker exec familiar-api rm -rf /app/static && docker cp $REMOTE_PATH/frontend/dist/. familiar-api:/app/static/"
fi

if [ "$DEPLOY_BACKEND" = true ]; then
    echo "Syncing migrations into container..."
    ssh jeff@$NAS_HOST "docker cp $REMOTE_PATH/backend/migrations/. familiar-api:/app/migrations/"

    echo "Syncing scripts into container..."
    ssh jeff@$NAS_HOST "docker cp $REMOTE_PATH/backend/scripts/. familiar-api:/app/scripts/"

    echo "Running database migrations..."
    ssh jeff@$NAS_HOST "docker exec -w /app -e PYTHONPATH=/app familiar-api alembic upgrade head" || {
        echo "Warning: Migration failed or no new migrations to apply"
    }
fi

# Restart again to pick up code copied via docker cp
echo "Restarting container with new code..."
ssh jeff@$NAS_HOST "docker restart familiar-api"

# Verify the container actually ends up with the code we just sent.
#
# `docker cp` MERGES: it overwrites files and never removes them, and it has no
# notion of newer or older. So any file left stale in $REMOTE_PATH silently
# replaces the container's copy — including a *newer* one baked into the image.
#
# That is not hypothetical. On 2026-09-03 this script pushed an `analysis.py`
# from two days earlier over the version in the running image, reverting the
# embedder to a torch implementation the image no longer installs. Embeddings
# switched themselves off, every library sync reported success having done
# nothing, and it took two stalls and an hour to find, because the only symptom
# was work not happening.
#
# Checks that every local file is present in the container at the same size.
# Size is enough: the failure mode is a wholly different revision of a file, not
# a one-byte edit, and it needs no checksum tool to agree across macOS and Linux.
#
# Extra files in the container are reported but not fatal. `docker cp` never
# deletes, so every module ever removed from the repo is still sitting in there —
# 55 of them as of this writing, including `chat.py`, which ADR-0048 deleted.
# They are inert unless something imports them, which is its own hazard, but that
# is a cleanup rather than a deploy failure.
if [ "$DEPLOY_BACKEND" = true ]; then
    echo "Verifying deployed code matches source..."
    # LC_ALL=C on both sides: macOS and Linux `sort` disagree on where `_` and
    # `/` fall in the default locale, so an unsorted-identically pair makes `comm`
    # report every file as differing while the sizes match exactly.
    LOCAL_MANIFEST=$(cd backend/app && find . -name '*.py' -not -path '*__pycache__*' \
        -exec stat -f '%N %z' {} \; 2>/dev/null | LC_ALL=C sort)
    REMOTE_MANIFEST=$(ssh jeff@$NAS_HOST "docker exec familiar-api sh -c \"cd /app/app && find . -name '*.py' -not -path '*__pycache__*' -exec stat -c '%n %s' {} \\; | LC_ALL=C sort\"" 2>/dev/null)

    if [ -z "$REMOTE_MANIFEST" ]; then
        echo "  WARNING: could not read the container's files; skipping verification"
    else
        MISSING=$(LC_ALL=C comm -23 <(echo "$LOCAL_MANIFEST") <(echo "$REMOTE_MANIFEST"))
        ORPHANS=$(LC_ALL=C comm -13 <(echo "$LOCAL_MANIFEST" | cut -d' ' -f1 | LC_ALL=C sort) \
                                    <(echo "$REMOTE_MANIFEST" | cut -d' ' -f1 | LC_ALL=C sort) | wc -l | tr -d ' ')
        if [ -n "$MISSING" ]; then
            echo ""
            echo "  MISMATCH — the container is not running the code in this checkout."
            echo "  Local files absent or a different size in the container:"
            echo "$MISSING" | head -20 | sed 's/^/    /'
            echo ""
            echo "  Most likely $REMOTE_PATH on $NAS_HOST holds a stale copy that"
            echo "  docker cp pushed over the image's newer one. Re-run this script;"
            echo "  if it persists, compare against the image directly:"
            echo "    docker run --rm --entrypoint sh <image> -c 'stat -c %s /app/app/services/analysis.py'"
            exit 1
        fi
        echo "  OK: $(echo "$LOCAL_MANIFEST" | wc -l | tr -d ' ') files match ($ORPHANS orphaned in container)"
    fi
fi

echo ""
echo "Done! Changes deployed in ${SECONDS}s"
echo "View at: http://$NAS_HOST:4400"
