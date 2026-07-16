#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source "$SCRIPT_DIR/start.sh"

command -v curl >/dev/null 2>&1
command -v python3 >/dev/null 2>&1

curl -fsS "http://127.0.0.1:${OPENCLAW_DEMO_PORT}/healthz"
printf '\n'
curl -fsS "${OPENCLAW_DEMO_PUBLIC_ORIGIN%/}/" >/dev/null

demo_compose exec -T openclaw-router-api python -c \
  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:3000/health', timeout=3).read().decode())"

demo_assert_plugin_loaded openclaw-router
demo_assert_plugin_loaded context-index
demo_assert_plugin_loaded task-compass

context_slot="$(demo_compose run --rm --no-deps openclaw-cli config get plugins.slots.contextEngine 2>&1)"
if [[ "$context_slot" != *"context-index"* ]]; then
  echo "Context Index slot check failed: $context_slot" >&2
  exit 1
fi

planner_output="$(
  demo_compose run --rm --no-deps --entrypoint python3 openclaw-cli \
    /opt/openclaw-plugins/task-compass/skills/task-compass/scripts/route_task.py \
    --goal "Plan a concise public demonstration of the three OpenClaw plugins."
)"
python3 -c \
  'import json,sys; value=json.load(sys.stdin); assert value.get("schema_version") == "1.0"' \
  <<<"$planner_output"

started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
smoke_output="$(mktemp -t openclaw-demo-smoke.XXXXXX.json)"
trap 'rm -f "$smoke_output"' EXIT

demo_compose run --rm --no-deps openclaw-cli agent \
  --agent main \
  --session-key "agent:main:public-demo-smoke-$(date +%s)" \
  --model openclaw-router/router-entry \
  --message "Reply exactly: OPENCLAW_DEMO_OK" \
  --json \
  --timeout "$OPENCLAW_DEMO_AGENT_TIMEOUT" | tee "$smoke_output"

route_found=false
for ((attempt = 1; attempt <= 10; attempt++)); do
  if demo_compose logs --since "$started_at" openclaw-router-api | grep -q 'route_decision'; then
    route_found=true
    break
  fi
  sleep 1
done
if [[ "$route_found" != true ]]; then
  echo "Router API did not emit a route_decision for the smoke task." >&2
  exit 1
fi

printf '\nDemo smoke passed.\nPublic Control UI: %s\n' "$(demo_public_url)"
