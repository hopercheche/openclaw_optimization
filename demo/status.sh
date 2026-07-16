#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$SCRIPT_DIR/start.sh"

demo_compose ps

if curl -fsS "http://127.0.0.1:${OPENCLAW_DEMO_PORT}/healthz" >/dev/null 2>&1; then
  printf '\nGateway health: OK\n'
  for plugin_id in openclaw-router context-index task-compass; do
    if ! demo_assert_plugin_loaded "$plugin_id"; then
      printf 'Plugin health: FAILED (%s)\n' "$plugin_id" >&2
    fi
  done
else
  printf '\nGateway health: unavailable on port %s\n' "$OPENCLAW_DEMO_PORT"
fi

if [[ "$OPENCLAW_DEMO_PUBLIC_ORIGIN" != *"replace-with"* && "$OPENCLAW_DEMO_GATEWAY_TOKEN" != *"replace-with"* ]]; then
  printf '\nPublic Control UI: %s\n' "$(demo_public_url)"
fi

if docker container inspect "$OPENCLAW_DEMO_NGROK_CONTAINER" >/dev/null 2>&1; then
  printf '\nngrok container: %s\n' "$OPENCLAW_DEMO_NGROK_CONTAINER"
  curl -fsS "http://127.0.0.1:${OPENCLAW_DEMO_NGROK_API_PORT}/api/tunnels" 2>/dev/null || true
  printf '\n'
fi
