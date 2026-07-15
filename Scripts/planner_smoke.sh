#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"

export EVALSCOPE_MODEL=mock
export EVALSCOPE_EVAL_TYPE=mock_llm
export EVALSCOPE_MODEL_ID=openclaw_planner_mock_smoke
export EVALSCOPE_LIMIT=1
export EVALSCOPE_JUDGE_STRATEGY=rule
export EVALSCOPE_OUTPUT_ROOT="${OPENCLAW_PLANNER_SMOKE_OUTPUT_ROOT:-$PROJECT_ROOT/outputs/planner-smoke}"
export PLANNER_GATEWAY_PORT="${OPENCLAW_PLANNER_SMOKE_PORT:-19110}"

exec bash "$SCRIPT_DIR/planner_mmlu_pro.sh"
