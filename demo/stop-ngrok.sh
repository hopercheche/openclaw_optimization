#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$SCRIPT_DIR/start.sh"

bash "$SCRIPT_DIR/stop.sh"

if docker container inspect "$OPENCLAW_DEMO_NGROK_CONTAINER" >/dev/null 2>&1; then
  docker rm -f "$OPENCLAW_DEMO_NGROK_CONTAINER" >/dev/null
  printf 'ngrok container removed: %s\n' "$OPENCLAW_DEMO_NGROK_CONTAINER"
else
  printf 'ngrok container is not present: %s\n' "$OPENCLAW_DEMO_NGROK_CONTAINER"
fi
