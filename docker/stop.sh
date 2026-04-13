#!/usr/bin/env bash
# Stop Familiar.

set -euo pipefail
cd "$(dirname "$0")"

COMPOSE_CMD="docker compose -f docker-compose.prod.yml"

if [ "$(uname)" = "Darwin" ]; then
    COMPOSE_CMD="$COMPOSE_CMD -f docker-compose.macos.yml"
fi

echo "Stopping Familiar..."
$COMPOSE_CMD down
echo "Stopped."
