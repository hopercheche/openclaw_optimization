#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
cd "$PROJECT_ROOT"

export ROUTER_DATASET_SLUG=mmlu-pro
export ROUTER_GATEWAY_PORT=18911
export EVALSCOPE_DATASET=mmlu_pro
export EVALSCOPE_DATASET_ARGS='{
  "mmlu_pro": {
    "subset_list": ["computer science"],
    "few_shot_num": 0
  }
}'
export EVALSCOPE_LIMIT="${EVALSCOPE_LIMIT:-5}"
export EVALSCOPE_JUDGE_STRATEGY="${EVALSCOPE_JUDGE_STRATEGY:-rule}"

source "$SCRIPT_DIR/lib/router_common.sh"
run_router_eval "$PROJECT_ROOT"
