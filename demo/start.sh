#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"

# Public Demo configuration. Edit these defaults before running this script, or
# override any value in the environment.
export OPENCLAW_DEMO_PUBLIC_ORIGIN="${OPENCLAW_DEMO_PUBLIC_ORIGIN:-https://replace-with-platform-url}"
export OPENCLAW_DEMO_PORT="${OPENCLAW_DEMO_PORT:-18789}"
export OPENCLAW_DEMO_GATEWAY_TOKEN="${OPENCLAW_DEMO_GATEWAY_TOKEN:-replace-with-demo-token}"
export OPENCLAW_DEMO_ALLOW_HTTP="${OPENCLAW_DEMO_ALLOW_HTTP:-false}"

export OPENCLAW_DEMO_MODEL_API_URL="${OPENCLAW_DEMO_MODEL_API_URL:-https://replace-with-provider/v1}"
export OPENCLAW_DEMO_MODEL_API_KEY="${OPENCLAW_DEMO_MODEL_API_KEY:-replace-with-dedicated-demo-key}"
export OPENCLAW_DEMO_MODEL_API="${OPENCLAW_DEMO_MODEL_API:-openai-responses}"
export OPENCLAW_DEMO_SMALL_MODEL="${OPENCLAW_DEMO_SMALL_MODEL:-qwen3.6-plus}"
export OPENCLAW_DEMO_MID_MODEL="${OPENCLAW_DEMO_MID_MODEL:-qwen3.7-plus}"
export OPENCLAW_DEMO_LARGE_MODEL="${OPENCLAW_DEMO_LARGE_MODEL:-qwen3.7-max}"
export OPENCLAW_DEMO_CONTEXT_WINDOW="${OPENCLAW_DEMO_CONTEXT_WINDOW:-131072}"
export OPENCLAW_DEMO_MAX_TOKENS="${OPENCLAW_DEMO_MAX_TOKENS:-8192}"
export OPENCLAW_DEMO_AGENT_TIMEOUT="${OPENCLAW_DEMO_AGENT_TIMEOUT:-600}"

export OPENCLAW_DEMO_IMAGE="${OPENCLAW_DEMO_IMAGE:-openclaw-demo:2026.6.11-three-plugins}"
export OPENCLAW_DEMO_BASE_IMAGE="${OPENCLAW_DEMO_BASE_IMAGE:-openclaw-router-gateway:2026.6.11-overlay}"
export OPENCLAW_ROUTER_API_IMAGE="${OPENCLAW_ROUTER_API_IMAGE:-openclaw-router-api:2026.6.11}"
export OPENCLAW_DEMO_COMPOSE_PROJECT="${OPENCLAW_DEMO_COMPOSE_PROJECT:-openclaw-public-demo}"
export OPENCLAW_DEMO_STATE_VOLUME="${OPENCLAW_DEMO_STATE_VOLUME:-openclaw-demo-state}"
export OPENCLAW_DEMO_SECRET_VOLUME="${OPENCLAW_DEMO_SECRET_VOLUME:-openclaw-demo-secrets}"
export OPENCLAW_DEMO_TZ="${OPENCLAW_DEMO_TZ:-Asia/Shanghai}"

export OPENCLAW_ROUTER_EMBEDDING_MODE="${OPENCLAW_ROUTER_EMBEDDING_MODE:-hash}"
export OPENCLAW_ROUTER_API_KEY="${OPENCLAW_ROUTER_API_KEY:-}"
export OPENCLAW_DEMO_ROUTER_CONFIDENCE_THRESHOLD="${OPENCLAW_DEMO_ROUTER_CONFIDENCE_THRESHOLD:-0.5}"
export OPENCLAW_DEMO_ROUTER_TIMEOUT_MS="${OPENCLAW_DEMO_ROUTER_TIMEOUT_MS:-5000}"
export OPENCLAW_DEMO_ROUTER_STRICT="${OPENCLAW_DEMO_ROUTER_STRICT:-true}"

export OPENCLAW_DEMO_CONTEXT_INDEX_MODE="${OPENCLAW_DEMO_CONTEXT_INDEX_MODE:-progressive}"
export OPENCLAW_DEMO_CONTEXT_INDEX_PROJECT_ID="${OPENCLAW_DEMO_CONTEXT_INDEX_PROJECT_ID:-public-demo}"
export OPENCLAW_DEMO_CONTEXT_INDEX_RECENT_MESSAGE_LIMIT="${OPENCLAW_DEMO_CONTEXT_INDEX_RECENT_MESSAGE_LIMIT:-8}"
export OPENCLAW_DEMO_CONTEXT_INDEX_MAX_SNIPPET_CHARS="${OPENCLAW_DEMO_CONTEXT_INDEX_MAX_SNIPPET_CHARS:-900}"
export OPENCLAW_DEMO_CONTEXT_INDEX_TOP_K="${OPENCLAW_DEMO_CONTEXT_INDEX_TOP_K:-8}"
export OPENCLAW_DEMO_CONTEXT_INDEX_CANDIDATE_K="${OPENCLAW_DEMO_CONTEXT_INDEX_CANDIDATE_K:-80}"
export OPENCLAW_DEMO_CONTEXT_INDEX_HALF_LIFE_DAYS="${OPENCLAW_DEMO_CONTEXT_INDEX_HALF_LIFE_DAYS:-30}"
export OPENCLAW_DEMO_PLANNER_TIMEOUT_MS="${OPENCLAW_DEMO_PLANNER_TIMEOUT_MS:-1500}"
export OPENCLAW_DEMO_PLANNER_MAX_PROMPT_CHARS="${OPENCLAW_DEMO_PLANNER_MAX_PROMPT_CHARS:-12000}"
export OPENCLAW_DEMO_TOOL_PROFILE="${OPENCLAW_DEMO_TOOL_PROFILE:-minimal}"

export OPENCLAW_DEMO_NGROK_AUTHTOKEN="${OPENCLAW_DEMO_NGROK_AUTHTOKEN:-replace-with-ngrok-authtoken}"
export OPENCLAW_DEMO_NGROK_IMAGE="${OPENCLAW_DEMO_NGROK_IMAGE:-ngrok/ngrok:latest}"
export OPENCLAW_DEMO_NGROK_CONTAINER="${OPENCLAW_DEMO_NGROK_CONTAINER:-openclaw-demo-ngrok}"
export OPENCLAW_DEMO_NGROK_API_PORT="${OPENCLAW_DEMO_NGROK_API_PORT:-4040}"

demo_compose() {
  docker compose \
    -f "$SCRIPT_DIR/docker-compose.yml" \
    -p "$OPENCLAW_DEMO_COMPOSE_PROJECT" \
    "$@"
}

demo_public_url() {
  python3 - "$OPENCLAW_DEMO_PUBLIC_ORIGIN" "$OPENCLAW_DEMO_GATEWAY_TOKEN" <<'PY'
import sys
from urllib.parse import quote

origin = sys.argv[1].rstrip("/")
token = quote(sys.argv[2], safe="")
print(f"{origin}/#token={token}")
PY
}

demo_assert_plugin_loaded() {
  local plugin_id="$1"
  local output
  output="$(demo_compose run --rm --no-deps openclaw-cli plugins inspect "$plugin_id" 2>&1)"
  printf '%s\n' "$output"
  if [[ "$output" != *"Status: loaded"* ]]; then
    echo "Plugin did not load: $plugin_id" >&2
    return 1
  fi
}

# Other demo scripts source this file to share the exact same configuration.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command not found: $1" >&2
    exit 1
  }
}

require_real_value() {
  local name="$1"
  local value="${!name:-}"
  if [[ -z "$value" || "$value" == *"replace-with"* ]]; then
    echo "Configure $name at the top of $SCRIPT_DIR/start.sh before starting the demo." >&2
    exit 1
  fi
}

require_command docker
require_command curl
require_command python3
docker compose version >/dev/null

require_real_value OPENCLAW_DEMO_PUBLIC_ORIGIN
require_real_value OPENCLAW_DEMO_GATEWAY_TOKEN
require_real_value OPENCLAW_DEMO_MODEL_API_URL
require_real_value OPENCLAW_DEMO_MODEL_API_KEY
require_real_value OPENCLAW_DEMO_SMALL_MODEL
require_real_value OPENCLAW_DEMO_MID_MODEL
require_real_value OPENCLAW_DEMO_LARGE_MODEL

export OPENCLAW_DEMO_PUBLIC_ORIGIN
OPENCLAW_DEMO_PUBLIC_ORIGIN="$(python3 - "$OPENCLAW_DEMO_PUBLIC_ORIGIN" "$OPENCLAW_DEMO_ALLOW_HTTP" <<'PY'
import sys
from urllib.parse import urlsplit

raw = sys.argv[1]
allow_http = sys.argv[2].strip().lower() in {"1", "true", "yes", "on"}
parsed = urlsplit(raw)
if parsed.scheme not in {"http", "https"} or not parsed.netloc:
    raise SystemExit("OPENCLAW_DEMO_PUBLIC_ORIGIN must be an HTTP or HTTPS origin")
if parsed.scheme == "http" and not allow_http:
    raise SystemExit(
        "HTTP origin is disabled by default; set OPENCLAW_DEMO_ALLOW_HTTP=true "
        "for an explicitly insecure public demo"
    )
if parsed.username or parsed.password or parsed.query or parsed.fragment:
    raise SystemExit("OPENCLAW_DEMO_PUBLIC_ORIGIN must not contain credentials, query, or fragment")
if parsed.path not in ("", "/"):
    raise SystemExit("OPENCLAW_DEMO_PUBLIC_ORIGIN must not contain a path")
print(f"{parsed.scheme}://{parsed.netloc}")
PY
)"

if ! [[ "$OPENCLAW_DEMO_PORT" =~ ^[0-9]+$ ]] || ((OPENCLAW_DEMO_PORT < 1 || OPENCLAW_DEMO_PORT > 65535)); then
  echo "OPENCLAW_DEMO_PORT must be between 1 and 65535." >&2
  exit 1
fi

missing_images=()
for image in "$OPENCLAW_DEMO_IMAGE" "$OPENCLAW_ROUTER_API_IMAGE"; do
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    missing_images+=("$image")
  fi
done
if ((${#missing_images[@]} > 0)); then
  printf 'Missing required image: %s\n' "${missing_images[@]}" >&2
  echo "Build the Demo image first with: bash $SCRIPT_DIR/build.sh" >&2
  exit 1
fi

demo_compose config --quiet

running_gateway_id="$(demo_compose ps -q openclaw-gateway 2>/dev/null || true)"
if [[ -z "$running_gateway_id" ]]; then
  if ! python3 - "$OPENCLAW_DEMO_PORT" <<'PY'
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    sock.bind(("0.0.0.0", port))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
  then
    echo "Host port $OPENCLAW_DEMO_PORT is already in use." >&2
    docker ps \
      --filter "publish=$OPENCLAW_DEMO_PORT" \
      --format 'Docker owner: {{.Names}}  {{.Ports}}' >&2 || true
    echo "Inspect other listeners with: sudo ss -ltnp 'sport = :$OPENCLAW_DEMO_PORT'" >&2
    echo "Stop the existing owner or choose another OPENCLAW_DEMO_PORT and matching public forwarding URL." >&2
    exit 1
  fi
fi

show_failure_logs() {
  local status="$?"
  if ((status != 0)); then
    demo_compose logs --tail=200 openclaw-demo-init openclaw-router-api openclaw-gateway >&2 || true
  fi
  exit "$status"
}
trap show_failure_logs ERR

demo_compose up -d --remove-orphans openclaw-router-api openclaw-demo-init openclaw-gateway

for ((attempt = 1; attempt <= 90; attempt++)); do
  if curl -fsS "http://127.0.0.1:${OPENCLAW_DEMO_PORT}/healthz" >/dev/null 2>&1; then
    break
  fi
  if ((attempt == 90)); then
    echo "OpenClaw Gateway did not become healthy within 180 seconds." >&2
    exit 1
  fi
  sleep 2
done

demo_compose exec -T openclaw-router-api python -c \
  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:3000/health', timeout=3).read().decode())"

demo_assert_plugin_loaded openclaw-router
demo_assert_plugin_loaded context-index
demo_assert_plugin_loaded task-compass

context_slot="$(demo_compose run --rm --no-deps openclaw-cli config get plugins.slots.contextEngine 2>&1)"
printf '%s\n' "$context_slot"
if [[ "$context_slot" != *"context-index"* ]]; then
  echo "Context Index is not configured as the context engine." >&2
  exit 1
fi

device_auth="$(demo_compose run --rm --no-deps openclaw-cli config get gateway.controlUi.dangerouslyDisableDeviceAuth 2>&1)"
printf '%s\n' "$device_auth"
if [[ "$device_auth" != *"true"* ]]; then
  echo "Control UI device authentication bypass is not enabled." >&2
  exit 1
fi

trap - ERR
printf '\nOpenClaw public Demo is ready.\n'
printf 'Local health: http://127.0.0.1:%s/healthz\n' "$OPENCLAW_DEMO_PORT"
printf 'Public Control UI: %s\n' "$(demo_public_url)"
printf '\nWARNING: this link grants full shared Control UI access. Use a dedicated, quota-limited model key.\n'
