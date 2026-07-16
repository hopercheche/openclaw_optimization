#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"

# Load image names from the same configuration used by start.sh.
source "$SCRIPT_DIR/start.sh"

PLANNER_VERSION="${OPENCLAW_PLANNER_VERSION:-0.3.0}"
PLANNER_ROOT="${OPENCLAW_PLANNER_SOURCE_DIR:-$PROJECT_ROOT/openclaw-planner}"
CONTEXT_INDEX_ROOT="${OPENCLAW_CONTEXT_INDEX_SOURCE_DIR:-$PROJECT_ROOT/openclaw-architechture/context_index}"
BUILD_ROOT="$(mktemp -d -t openclaw-demo-build.XXXXXX)"
PLANNER_BUILD_ROOT="$(mktemp -d -t openclaw-demo-planner.XXXXXX)"

cleanup() {
  rm -rf "$BUILD_ROOT" "$PLANNER_BUILD_ROOT"
}
trap cleanup EXIT

command -v docker >/dev/null 2>&1
command -v python3 >/dev/null 2>&1
docker image inspect "$OPENCLAW_DEMO_BASE_IMAGE" >/dev/null
docker image inspect "$OPENCLAW_ROUTER_API_IMAGE" >/dev/null

test -f "$CONTEXT_INDEX_ROOT/openclaw.plugin.json"
test -f "$CONTEXT_INDEX_ROOT/index.ts"
test -f "$PLANNER_ROOT/scripts/build_integrations.py"
test -f "$PLANNER_ROOT/scripts/validate_integrations.py"

python3 "$PLANNER_ROOT/scripts/build_integrations.py" \
  --root "$PLANNER_ROOT" \
  --output-dir "$PLANNER_BUILD_ROOT" \
  --version "$PLANNER_VERSION"

python3 "$PLANNER_ROOT/scripts/validate_integrations.py" \
  --root "$PLANNER_ROOT" \
  --build-dir "$PLANNER_BUILD_ROOT"

PLANNER_BUNDLE="$PLANNER_BUILD_ROOT/task-compass-openclaw-native-v${PLANNER_VERSION}"
test -f "$PLANNER_BUNDLE/index.mjs"
test -f "$PLANNER_BUNDLE/skills/task-compass/scripts/route_task.py"

cp "$SCRIPT_DIR/Dockerfile" "$BUILD_ROOT/Dockerfile"
cp "$SCRIPT_DIR/init.mjs" "$BUILD_ROOT/init.mjs"
cp -a "$CONTEXT_INDEX_ROOT" "$BUILD_ROOT/context-index"
cp -a "$PLANNER_BUNDLE" "$BUILD_ROOT/task-compass"

docker build \
  --build-arg "BASE_IMAGE=$OPENCLAW_DEMO_BASE_IMAGE" \
  --label "org.opencontainers.image.base.name=$OPENCLAW_DEMO_BASE_IMAGE" \
  --label "org.opencontainers.image.version=2026.6.11-three-plugins" \
  --tag "$OPENCLAW_DEMO_IMAGE" \
  --file "$BUILD_ROOT/Dockerfile" \
  "$BUILD_ROOT"

docker image inspect "$OPENCLAW_DEMO_IMAGE" \
  --format 'Built {{.RepoTags}} from {{index .Config.Labels "org.opencontainers.image.base.name"}} ({{.Id}})'
