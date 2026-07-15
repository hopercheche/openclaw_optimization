#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"

BASE_IMAGE="${OPENCLAW_PLANNER_BASE_IMAGE:-openclaw-baseline:2026.6.11-srcsnap}"
OUTPUT_IMAGE="${OPENCLAW_PLANNER_IMAGE:-openclaw-planner:2026.6.11-overlay}"
SOURCE_ROOT="${OPENCLAW_PLANNER_SOURCE_DIR:-$PROJECT_ROOT/openclaw-planner}"
VERSION="${OPENCLAW_PLANNER_VERSION:-0.3.0}"
DOCKERFILE="$SCRIPT_DIR/docker/planner-overlay.Dockerfile"
BUILD_ROOT="$(mktemp -d -t openclaw-planner-build.XXXXXX)"

cleanup() {
  rm -rf "$BUILD_ROOT"
}
trap cleanup EXIT

docker image inspect "$BASE_IMAGE" >/dev/null
test -f "$SOURCE_ROOT/integrations/openclaw-native/openclaw.plugin.json"
test -f "$SOURCE_ROOT/scripts/build_integrations.py"
test -f "$SOURCE_ROOT/scripts/validate_integrations.py"

python3 "$SOURCE_ROOT/scripts/build_integrations.py" \
  --root "$SOURCE_ROOT" \
  --output-dir "$BUILD_ROOT" \
  --version "$VERSION"

python3 "$SOURCE_ROOT/scripts/validate_integrations.py" \
  --root "$SOURCE_ROOT" \
  --build-dir "$BUILD_ROOT"

BUNDLE_DIR="$BUILD_ROOT/task-compass-openclaw-native-v${VERSION}"
test -f "$BUNDLE_DIR/index.mjs"
test -f "$BUNDLE_DIR/router-bridge.mjs"
test -f "$BUNDLE_DIR/skills/task-compass/scripts/route_task.py"

docker build \
  --build-arg "BASE_IMAGE=$BASE_IMAGE" \
  --label "org.opencontainers.image.base.name=$BASE_IMAGE" \
  --label "org.opencontainers.image.source.path=openclaw-planner/integrations/openclaw-native" \
  --label "org.opencontainers.image.version=$VERSION" \
  --tag "$OUTPUT_IMAGE" \
  --file "$DOCKERFILE" \
  "$BUNDLE_DIR"

docker image inspect "$OUTPUT_IMAGE" \
  --format 'Built {{.RepoTags}} from {{index .Config.Labels "org.opencontainers.image.base.name"}} ({{.Id}})'
