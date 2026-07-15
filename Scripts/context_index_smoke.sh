#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"

export EVALSCOPE_MODEL=mock
export EVALSCOPE_EVAL_TYPE=mock_llm
export EVALSCOPE_MODEL_ID=openclaw_context_index_mock_smoke
export EVALSCOPE_LIMIT=1
export EVALSCOPE_JUDGE_STRATEGY=rule
export EVALSCOPE_OUTPUT_ROOT="${OPENCLAW_CONTEXT_INDEX_SMOKE_OUTPUT_ROOT:-$PROJECT_ROOT/outputs/context-index-smoke}"
export CONTEXT_INDEX_GATEWAY_PORT="${OPENCLAW_CONTEXT_INDEX_SMOKE_PORT:-19010}"

exec bash "$SCRIPT_DIR/context_index_mmlu_pro.sh"
