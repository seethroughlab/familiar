#!/usr/bin/env bash
# Update Familiar to the latest version.
# Usage: ./update.sh

set -euo pipefail
cd "$(dirname "$0")"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

if ! docker info &>/dev/null; then
    echo -e "${RED}Docker is not running.${NC}"
    echo "Open Docker Desktop and wait for it to finish starting, then try again."
    exit 1
fi

echo -e "${BOLD}Updating Familiar...${NC}"
echo ""

# Pull the latest Docker image
echo "Pulling latest version..."
docker pull ghcr.io/seethroughlab/familiar:latest
echo ""

# Download and apply the latest scripts
echo "Updating setup scripts..."
WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT

if curl -fsSL --connect-timeout 15 \
    "https://github.com/seethroughlab/familiar/archive/refs/heads/main.zip" \
    -o "$WORK_DIR/familiar.zip" 2>/dev/null; then

    unzip -q "$WORK_DIR/familiar.zip" -d "$WORK_DIR"

    # Copy docker/ files, preserving the user's .env
    for f in "$WORK_DIR/familiar-main/docker/"*; do
        fname=$(basename "$f")
        [ "$fname" = ".env" ] && continue
        cp "$f" "./$fname"
    done
    chmod +x ./*.sh 2>/dev/null || true

    echo "Scripts updated."
else
    echo -e "${YELLOW}Note:${NC} Could not reach GitHub to update scripts. Continuing with the new Docker image."
fi
echo ""

# Stop and restart with the new image
echo "Restarting Familiar..."
./stop.sh 2>/dev/null || true
echo ""
exec ./start.sh "$@"
