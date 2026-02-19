#!/bin/bash
# Quick deploy to NAS for development testing
# Builds frontend locally and rsyncs to NAS, then restarts container
# Usage: ./scripts/deploy-dev.sh [--backend-only] [--frontend-only]
set -e

NAS_HOST="${NAS_HOST:-openmediavault}"
REMOTE_PATH="/opt/familiar"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

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
    cd frontend && npm run build && cd ..

    echo "Syncing frontend to $NAS_HOST..."
    rsync -avz --delete \
        --exclude 'node_modules' \
        --exclude '.git' \
        frontend/dist/ root@$NAS_HOST:$REMOTE_PATH/frontend/dist/

fi

# Sync backend if needed
if [ "$DEPLOY_BACKEND" = true ]; then
    echo "Syncing backend to $NAS_HOST..."
    # Remove stale models.py if it exists alongside models/ package
    # Python prefers packages over modules — having both causes import confusion
    ssh root@$NAS_HOST "test -d $REMOTE_PATH/backend/app/db/models && rm -f $REMOTE_PATH/backend/app/db/models.py" 2>/dev/null || true
    rsync -avz \
        --exclude '__pycache__' \
        --exclude '.venv' \
        --exclude '*.pyc' \
        backend/app/ root@$NAS_HOST:$REMOTE_PATH/backend/app/

    echo "Syncing migrations to $NAS_HOST..."
    rsync -avz \
        --exclude '__pycache__' \
        --exclude '*.pyc' \
        backend/migrations/ root@$NAS_HOST:$REMOTE_PATH/backend/migrations/
fi

echo "Restarting container..."
ssh root@$NAS_HOST "docker restart familiar-api"

# Install any packages not in the base image (temporary until image rebuild)
echo "Installing additional dependencies..."
ssh root@$NAS_HOST "docker exec familiar-api sh -c 'which pg_dump > /dev/null 2>&1 || apt-get update -qq && apt-get install -y -qq postgresql-client > /dev/null 2>&1'" || true
ssh root@$NAS_HOST "docker exec familiar-api sh -c 'which deno > /dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq curl unzip > /dev/null 2>&1 && curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh)'" || true
ssh root@$NAS_HOST "docker exec familiar-api uv pip install 'curl_cffi>=0.7.0' 'trafilatura>=1.6.0' 'boto3>=1.34.0' 'yt-dlp[default]' 'bcrypt>=4.0.0' 'pyloudnorm>=0.1.0' 'soundfile>=0.12.0' 'basic-pitch[onnx]>=0.3.0' 'matplotlib>=3.5.0' --python /app/.venv/bin/python -q" || true

if [ "$DEPLOY_BACKEND" = true ]; then
    echo "Syncing migrations into container..."
    ssh root@$NAS_HOST "docker cp $REMOTE_PATH/backend/migrations/. familiar-api:/app/migrations/"

    echo "Running database migrations..."
    ssh root@$NAS_HOST "docker exec -w /app -e PYTHONPATH=/app familiar-api alembic upgrade head" || {
        echo "Warning: Migration failed or no new migrations to apply"
    }
fi

echo ""
echo "Done! Changes deployed in ${SECONDS}s"
echo "View at: http://$NAS_HOST:4400"
