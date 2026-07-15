#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
cd "$PROJECT_ROOT"

export CONTEXT_INDEX_DATASET_SLUG=gpqa-diamond
export CONTEXT_INDEX_GATEWAY_PORT="${CONTEXT_INDEX_GATEWAY_PORT:-19012}"
export EVALSCOPE_DATASET=gpqa_diamond
export EVALSCOPE_DATASET_ARGS='{
  "gpqa_diamond": {
    "few_shot_num": 0
  }
}'
export EVALSCOPE_LIMIT="${EVALSCOPE_LIMIT:-5}"
export EVALSCOPE_JUDGE_STRATEGY="${EVALSCOPE_JUDGE_STRATEGY:-rule}"

source "$SCRIPT_DIR/lib/context_index_common.sh"
run_context_index_eval "$PROJECT_ROOT"
