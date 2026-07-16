#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$SCRIPT_DIR/start.sh"

if [[ -z "$OPENCLAW_DEMO_NGROK_AUTHTOKEN" || "$OPENCLAW_DEMO_NGROK_AUTHTOKEN" == *"replace-with"* ]]; then
  echo "Configure OPENCLAW_DEMO_NGROK_AUTHTOKEN at the top of demo/start.sh." >&2
  exit 1
fi

if ! [[ "$OPENCLAW_DEMO_NGROK_API_PORT" =~ ^[0-9]+$ ]] || \
  ((OPENCLAW_DEMO_NGROK_API_PORT < 1 || OPENCLAW_DEMO_NGROK_API_PORT > 65535)); then
  echo "OPENCLAW_DEMO_NGROK_API_PORT must be between 1 and 65535." >&2
  exit 1
fi

docker image inspect "$OPENCLAW_DEMO_NGROK_IMAGE" >/dev/null 2>&1 || \
  docker pull "$OPENCLAW_DEMO_NGROK_IMAGE"

if docker container inspect "$OPENCLAW_DEMO_NGROK_CONTAINER" >/dev/null 2>&1; then
  docker rm -f "$OPENCLAW_DEMO_NGROK_CONTAINER" >/dev/null
fi

docker run -d \
  --name "$OPENCLAW_DEMO_NGROK_CONTAINER" \
  --restart unless-stopped \
  --add-host host.docker.internal:host-gateway \
  -p "127.0.0.1:${OPENCLAW_DEMO_NGROK_API_PORT}:4040" \
  -e "NGROK_AUTHTOKEN=$OPENCLAW_DEMO_NGROK_AUTHTOKEN" \
  "$OPENCLAW_DEMO_NGROK_IMAGE" \
  http "http://host.docker.internal:${OPENCLAW_DEMO_PORT}" >/dev/null

ngrok_failure() {
  local status="$?"
  if ((status != 0)); then
    docker logs --tail=100 "$OPENCLAW_DEMO_NGROK_CONTAINER" >&2 || true
  fi
  exit "$status"
}
trap ngrok_failure ERR

ngrok_origin=""
for ((attempt = 1; attempt <= 60; attempt++)); do
  ngrok_origin="$(
    curl -fsS "http://127.0.0.1:${OPENCLAW_DEMO_NGROK_API_PORT}/api/tunnels" 2>/dev/null |
      python3 -c '
import json
import sys

try:
    payload = json.load(sys.stdin)
except Exception:
    raise SystemExit(0)

urls = [
    tunnel.get("public_url", "")
    for tunnel in payload.get("tunnels", [])
    if isinstance(tunnel, dict)
]
print(next((url.rstrip("/") for url in urls if url.startswith("https://")), ""))
'
  )"
  if [[ -n "$ngrok_origin" ]]; then
    break
  fi
  if ((attempt == 60)); then
    echo "ngrok did not publish an HTTPS tunnel within 120 seconds." >&2
    exit 1
  fi
  sleep 2
done

export OPENCLAW_DEMO_PUBLIC_ORIGIN="$ngrok_origin"
export OPENCLAW_DEMO_ALLOW_HTTP=false

printf 'ngrok HTTPS origin: %s\n' "$OPENCLAW_DEMO_PUBLIC_ORIGIN"
bash "$SCRIPT_DIR/start.sh"

trap - ERR
printf '\nngrok Control UI: %s\n' "$(demo_public_url)"
