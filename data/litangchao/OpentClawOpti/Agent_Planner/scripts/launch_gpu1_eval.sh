#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-base-vs-lora-heldout}"
BASE_MODEL="${BASE_MODEL:-/home/litangchao/.cache/huggingface/hub/models--Qwen--Qwen2.5-3B-Instruct/snapshots/aa8e72537993ba99e69dfaafa59ed015b17504d1}"
ADAPTER="${ADAPTER:-${ROOT}/models/20260623T063028Z-qwen25-3b-gpu1-stream200k-5k/final_adapter}"
EVAL_FILE="${EVAL_FILE:-${ROOT}/processed/qwen_terminal_toolbench_sft.jsonl}"
OUT="${ROOT}/eval_runs/${RUN_ID}"
LOG="${ROOT}/logs/${RUN_ID}.log"
PIDFILE="${ROOT}/logs/${RUN_ID}.pid"

mkdir -p "${OUT}" "${ROOT}/logs"

COMMAND=(
  /home/litangchao/miniconda3/bin/conda run -n AgentOpti python
  "${ROOT}/scripts/evaluate_planner_sft.py"
  --base-model "${BASE_MODEL}"
  --adapter "${ADAPTER}"
  --eval-file "${EVAL_FILE}"
  --output-dir "${OUT}"
  --start-line "${START_LINE:-300001}"
  --loss-examples "${LOSS_EXAMPLES:-64}"
  --generation-examples "${GENERATION_EXAMPLES:-16}"
  --max-seq-length "${MAX_SEQ_LENGTH:-1024}"
  --max-new-tokens "${MAX_NEW_TOKENS:-256}"
  --dtype "${DTYPE:-bf16}"
  --require-cuda
)

if [[ "${SKIP_BASE:-0}" == "1" ]]; then
  COMMAND+=(--skip-base)
fi

setsid -f bash -c '
  pidfile="$1"
  log="$2"
  shift 2
  echo $$ > "$pidfile"
  exec env CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-1}" PYTHONUNBUFFERED=1 "$@" > "$log" 2>&1
' bash "${PIDFILE}" "${LOG}" "${COMMAND[@]}"

echo "${RUN_ID}" > "${ROOT}/logs/latest_eval_run_id.txt"
echo "RUN_ID=${RUN_ID}"
echo "OUT=${OUT}"
echo "LOG=${LOG}"
echo "PIDFILE=${PIDFILE}"
