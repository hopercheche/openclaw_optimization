#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

BASE_IMAGE="${OPENCLAW_ROUTER_BASE_IMAGE:-openclaw-baseline:2026.6.11-srcsnap}"
GATEWAY_IMAGE="${OPENCLAW_ROUTER_GATEWAY_IMAGE:-openclaw-router-gateway:local}"
ROUTER_API_IMAGE="${OPENCLAW_ROUTER_API_IMAGE:-openclaw-router-api:local}"
INSTALL_BGE="${OPENCLAW_ROUTER_INSTALL_BGE:-0}"
PIP_INDEX_URL="${OPENCLAW_ROUTER_PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple}"
ROUTER_API_HTTP_PROXY="${OPENCLAW_ROUTER_BUILD_HTTP_PROXY:-}"

router_api_proxy_args=()
if [[ -n "$ROUTER_API_HTTP_PROXY" ]]; then
  router_api_proxy_args+=(
    --build-arg "HTTP_PROXY=$ROUTER_API_HTTP_PROXY"
    --build-arg "HTTPS_PROXY=$ROUTER_API_HTTP_PROXY"
  )
fi

docker image inspect "$BASE_IMAGE" >/dev/null

docker build \
  --build-arg "BASE_IMAGE=$BASE_IMAGE" \
  --tag "$GATEWAY_IMAGE" \
  --file "$SCRIPT_DIR/docker/router-overlay.Dockerfile" \
  "$PROJECT_ROOT"

docker build \
  "${router_api_proxy_args[@]}" \
  --build-arg "INSTALL_BGE=$INSTALL_BGE" \
  --build-arg "PIP_INDEX_URL=$PIP_INDEX_URL" \
  --tag "$ROUTER_API_IMAGE" \
  --file "$PROJECT_ROOT/openclaw_router/openclaw-router-plugin/deploy/Dockerfile" \
  "$PROJECT_ROOT/openclaw_router/openclaw-router-plugin/deploy"

printf 'Built %s from %s\n' "$GATEWAY_IMAGE" "$BASE_IMAGE"
printf 'Built %s (INSTALL_BGE=%s)\n' "$ROUTER_API_IMAGE" "$INSTALL_BGE"
