#!/usr/bin/env bash
# Start Familiar — detects macOS and applies the correct Docker Compose config.
#
# Usage:
#   ./start.sh          # Start in background
#   ./start.sh --logs   # Start and follow logs

set -euo pipefail
cd "$(dirname "$0")"

# Bump this when scripts or compose files change in a way that
# requires users to re-download. The value should match the release tag.
SCRIPT_VERSION="2026.04.13"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

# --- Pre-flight checks ---

# Docker running?
if ! docker info &>/dev/null; then
    echo -e "${RED}Docker is not running.${NC}"
    echo "Open Docker Desktop and wait for it to finish starting, then try again."
    exit 1
fi

# .env exists?
if [ ! -f .env ]; then
    echo -e "${RED}.env file not found.${NC}"
    echo ""
    echo "Create it from the example:"
    echo "  cp .env.example .env"
    echo ""
    echo "Then edit .env and set MUSIC_LIBRARY_PATH to your music folder, e.g.:"
    echo "  MUSIC_LIBRARY_PATH=~/Music"
    exit 1
fi

# MUSIC_LIBRARY_PATH set?
if grep -q '^MUSIC_LIBRARY_PATH=' .env; then
    MUSIC_PATH=$(grep '^MUSIC_LIBRARY_PATH=' .env | head -1 | cut -d= -f2-)
    if [ -z "$MUSIC_PATH" ]; then
        echo -e "${YELLOW}Warning:${NC} MUSIC_LIBRARY_PATH is not set in .env"
        echo "Set it to your music folder path, e.g.:"
        echo "  MUSIC_LIBRARY_PATH=~/Music"
        echo ""
    else
        # Expand tilde — Docker Compose does not expand ~ from .env variable substitution
        MUSIC_PATH="${MUSIC_PATH/#\~/$HOME}"
        if [ ! -d "$MUSIC_PATH" ]; then
            echo -e "${YELLOW}Warning:${NC} MUSIC_LIBRARY_PATH=$MUSIC_PATH does not exist."
            echo "Familiar will start, but won't find any music until the path is corrected in .env"
            echo ""
        fi
        # Export so Docker Compose picks up the absolute path instead of the raw ~ value
        export MUSIC_LIBRARY_PATH="$MUSIC_PATH"
    fi
fi

# RAM check (macOS only)
if [ "$(uname)" = "Darwin" ]; then
    RAM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
    RAM_GB=$((RAM_BYTES / 1073741824))
    if [ "$RAM_GB" -le 8 ] && [ "$RAM_GB" -gt 0 ]; then
        if ! grep -q '^DISABLE_CLAP_EMBEDDINGS=true' .env 2>/dev/null; then
            echo -e "${YELLOW}Note:${NC} Your Mac has ${RAM_GB}GB RAM. The CLAP audio embedding model"
            echo "uses ~4GB at peak and may cause out-of-memory issues."
            echo ""
            echo "To avoid this, add the following line to your .env file:"
            echo "  DISABLE_CLAP_EMBEDDINGS=true"
            echo ""
            echo "This disables semantic search embeddings but keeps all other audio"
            echo "analysis (BPM, key detection, energy, mood, etc.)."
            echo ""
        fi
    fi
fi

# --- Build compose command ---

COMPOSE_CMD="docker compose -f docker-compose.prod.yml"

if [ "$(uname)" = "Darwin" ]; then
    COMPOSE_CMD="$COMPOSE_CMD -f docker-compose.macos.yml"
fi

# --- Start ---

echo -e "${BOLD}Starting Familiar...${NC}"
$COMPOSE_CMD up -d

# --- Health check ---

# Get the port from .env or default to 4400
API_PORT=$(grep '^API_PORT=' .env 2>/dev/null | cut -d= -f2- || echo "4400")
API_PORT="${API_PORT:-4400}"
API_URL="http://localhost:${API_PORT}"

if [ "${1:-}" = "--logs" ]; then
    $COMPOSE_CMD logs -f
else
    echo ""
    echo "Waiting for Familiar to be ready..."
    for i in $(seq 1 24); do
        STATUS=$(curl -s -o /dev/null -w '%{http_code}' "${API_URL}/api/v1/health" 2>/dev/null || echo "000")
        if [ "$STATUS" = "200" ]; then
            echo ""
            echo -e "${GREEN}Familiar is running!${NC}"
            echo ""
            echo "  Open ${BOLD}${API_URL}${NC} in your browser"
            echo ""
            echo "  First time? Set API keys in your .env file, then open"
            echo "  ${BOLD}Settings${NC} (gear icon) to configure your library."

            # Check if scripts are outdated compared to the Docker image
            IMAGE_VERSION=$(docker exec familiar-api cat /app/VERSION 2>/dev/null || echo "")
            if [ -n "$IMAGE_VERSION" ] && [ "$IMAGE_VERSION" != "dev" ] && [ "$IMAGE_VERSION" != "$SCRIPT_VERSION" ]; then
                echo ""
                echo -e "${YELLOW}Note:${NC} Your Docker image ($IMAGE_VERSION) is newer than these"
                echo "scripts ($SCRIPT_VERSION). You can usually ignore this, but if you"
                echo "run into issues, download the latest scripts from:"
                echo "  https://github.com/seethroughlab/familiar/archive/refs/heads/master.zip"
            fi

            exit 0
        fi
        printf "."
        sleep 5
    done

    # Health check failed — diagnose
    echo ""
    echo -e "${RED}Familiar did not become healthy within 2 minutes.${NC}"
    echo ""

    # Show which containers are unhealthy
    UNHEALTHY=$($COMPOSE_CMD ps --format '{{.Name}} {{.Status}}' 2>/dev/null | grep -iv "healthy\|running" || true)
    if [ -n "$UNHEALTHY" ]; then
        echo "Problem containers:"
        echo "$UNHEALTHY"
        echo ""
    fi

    echo "Check the logs for errors:"
    echo "  cd docker && $COMPOSE_CMD logs --tail=30"
    exit 1
fi
