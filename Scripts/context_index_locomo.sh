#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
cd "$PROJECT_ROOT"

export CONTEXT_INDEX_DATASET_SLUG=locomo
export CONTEXT_INDEX_GATEWAY_PORT="${CONTEXT_INDEX_GATEWAY_PORT:-19015}"
export EVALSCOPE_DATASET=locomo
export EVALSCOPE_DATASET_ARGS='{
  "locomo": {
    "subset_list": ["qa"],
    "few_shot_num": 0,
    "extra_params": {
      "eval_mode": "long_context"
    }
  }
}'
export EVALSCOPE_LIMIT="${EVALSCOPE_LIMIT:-1}"
export EVALSCOPE_JUDGE_STRATEGY="${EVALSCOPE_JUDGE_STRATEGY:-rule}"

source "$SCRIPT_DIR/lib/context_index_common.sh"
run_context_index_eval "$PROJECT_ROOT"
