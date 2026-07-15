#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"

BASE_IMAGE="${OPENCLAW_CONTEXT_INDEX_BASE_IMAGE:-openclaw-baseline:2026.6.11-srcsnap}"
OUTPUT_IMAGE="${OPENCLAW_CONTEXT_INDEX_IMAGE:-openclaw-context-index:2026.6.11-overlay}"
PLUGIN_DIR="${OPENCLAW_CONTEXT_INDEX_SOURCE_DIR:-$PROJECT_ROOT/openclaw-architechture/context_index}"
DOCKERFILE="$SCRIPT_DIR/docker/context-index-overlay.Dockerfile"

docker image inspect "$BASE_IMAGE" >/dev/null
test -f "$PLUGIN_DIR/openclaw.plugin.json"
test -f "$PLUGIN_DIR/index.ts"
test -d "$PLUGIN_DIR/src"

docker build \
  --build-arg "BASE_IMAGE=$BASE_IMAGE" \
  --label "org.opencontainers.image.base.name=$BASE_IMAGE" \
  --label "org.opencontainers.image.source.path=openclaw-architechture/context_index" \
  --tag "$OUTPUT_IMAGE" \
  --file "$DOCKERFILE" \
  "$PLUGIN_DIR"

docker image inspect "$OUTPUT_IMAGE" --format 'Built {{.RepoTags}} from {{index .Config.Labels "org.opencontainers.image.base.name"}} ({{.Id}})'
