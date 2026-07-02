#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner"
CONDA="/home/litangchao/miniconda3/bin/conda"
MODEL="${MODEL:-/home/litangchao/.cache/huggingface/hub/models--Qwen--Qwen2.5-3B-Instruct/snapshots/aa8e72537993ba99e69dfaafa59ed015b17504d1}"
TRAIN_FILE="${TRAIN_FILE:-${ROOT}/processed/qwen_terminal_toolbench_sft_jsononly_200k.jsonl}"
ADAPTER_INIT="${ADAPTER_INIT:-${ROOT}/models/20260623T063028Z-qwen25-3b-gpu1-stream200k-5k/final_adapter}"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-qwen25-3b-gpu1-jsononly-stage2-1k}"
OUT_DIR="${ROOT}/models/${RUN_ID}"
LOG_DIR="${ROOT}/logs"
LOG_FILE="${LOG_DIR}/${RUN_ID}.log"
PID_FILE="${LOG_DIR}/${RUN_ID}.pid"

mkdir -p "${OUT_DIR}" "${LOG_DIR}"

if [ ! -e /dev/nvidia1 ]; then
  echo "GPU1 is not exposed: /dev/nvidia1 is missing." | tee "${LOG_FILE}"
  echo "Run this launcher outside the default Codex sandbox." | tee -a "${LOG_FILE}"
  exit 2
fi

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-1}"
export TOKENIZERS_PARALLELISM=false

setsid -f /bin/bash -lc "exec '${CONDA}' run -n AgentOpti python '${ROOT}/scripts/train_planner_sft.py' \
  --model '${MODEL}' \
  --adapter-init '${ADAPTER_INIT}' \
  --train-file '${TRAIN_FILE}' \
  --output-dir '${OUT_DIR}' \
  --max-steps ${MAX_STEPS:-1000} \
  --max-train-samples ${MAX_TRAIN_SAMPLES:-200000} \
  --max-seq-length ${MAX_SEQ_LENGTH:-1024} \
  --per-device-train-batch-size ${BATCH_SIZE:-1} \
  --gradient-accumulation-steps ${GRAD_ACCUM:-8} \
  --learning-rate ${LEARNING_RATE:-1e-4} \
  --warmup-steps ${WARMUP_STEPS:-50} \
  --logging-steps ${LOGGING_STEPS:-10} \
  --save-steps ${SAVE_STEPS:-250} \
  --streaming \
  --shuffle-buffer ${SHUFFLE_BUFFER:-10000} \
  --bf16 \
  --require-cuda \
  >'${LOG_FILE}' 2>&1"

sleep 2
pgrep -f "${ROOT}/scripts/train_planner_sft.py.*${OUT_DIR}" | tail -1 > "${PID_FILE}" || true
echo "${RUN_ID}" > "${LOG_DIR}/latest_jsononly_train_run_id.txt"
echo "started json-only planner training"
echo "run_id=${RUN_ID}"
echo "pid=${PID_FILE}"
echo "log=${LOG_FILE}"
echo "output=${OUT_DIR}"
