#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/litangchao/OpenClawPOpti/data/litangchao/OpentClawOpti/Agent_Planner"
CONDA="/home/litangchao/miniconda3/bin/conda"
MODEL="/home/litangchao/.cache/huggingface/hub/models--Qwen--Qwen2.5-3B-Instruct/snapshots/aa8e72537993ba99e69dfaafa59ed015b17504d1"
TRAIN_FILE="${ROOT}/processed/qwen_terminal_toolbench_sft_sample.jsonl"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-qwen25-3b-gpu1-smoke"
OUT_DIR="${ROOT}/models/${RUN_ID}"
LOG_DIR="${ROOT}/logs"
LOG_FILE="${LOG_DIR}/${RUN_ID}.log"
PID_FILE="${LOG_DIR}/${RUN_ID}.pid"

mkdir -p "${OUT_DIR}" "${LOG_DIR}"

if [ ! -e /dev/nvidia1 ]; then
  echo "GPU1 is not exposed: /dev/nvidia1 is missing." | tee "${LOG_FILE}"
  echo "Run nvidia-smi and expose /dev/nvidia* before launching training." | tee -a "${LOG_FILE}"
  exit 2
fi

export CUDA_VISIBLE_DEVICES=1
export TOKENIZERS_PARALLELISM=false

setsid -f /bin/bash -lc "exec '${CONDA}' run -n AgentOpti python '${ROOT}/scripts/train_planner_sft.py' \
  --model "${MODEL}" \
  --train-file "${TRAIN_FILE}" \
  --output-dir "${OUT_DIR}" \
  --max-steps 50 \
  --max-train-samples 2000 \
  --max-seq-length 1024 \
  --per-device-train-batch-size 1 \
  --gradient-accumulation-steps 8 \
  --learning-rate 2e-4 \
  --warmup-steps 5 \
  --logging-steps 1 \
  --save-steps 25 \
  --lora-r 16 \
  --lora-alpha 32 \
  --bf16 \
  --require-cuda \
  >'${LOG_FILE}' 2>&1"

sleep 2
pgrep -f "${ROOT}/scripts/train_planner_sft.py.*${OUT_DIR}" | tail -1 > "${PID_FILE}" || true
echo "started training"
echo "pid=${PID_FILE}"
echo "log=${LOG_FILE}"
echo "output=${OUT_DIR}"
