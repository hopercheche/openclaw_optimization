#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
cd "$PROJECT_ROOT"

export ROUTER_DATASET_SLUG=acebench
export ROUTER_GATEWAY_PORT=18914
export EVALSCOPE_DATASET=acebench
export EVALSCOPE_DATASET_ARGS='{
  "acebench": {
    "subset_list": ["agent"],
    "few_shot_num": 0
  }
}'
export EVALSCOPE_LIMIT="${EVALSCOPE_LIMIT:-50}"
export EVALSCOPE_JUDGE_STRATEGY="${EVALSCOPE_JUDGE_STRATEGY:-rule}"

source "$SCRIPT_DIR/lib/router_common.sh"
run_router_eval "$PROJECT_ROOT"
