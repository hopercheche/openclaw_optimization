#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
cd "$PROJECT_ROOT"

if command -v conda >/dev/null 2>&1; then
  eval "$(conda shell.bash hook)"
elif [[ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]]; then
  source "$HOME/miniconda3/etc/profile.d/conda.sh"
elif [[ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]]; then
  source "$HOME/anaconda3/etc/profile.d/conda.sh"
elif [[ -f "/opt/conda/etc/profile.d/conda.sh" ]]; then
  source "/opt/conda/etc/profile.d/conda.sh"
else
  echo "Conda was not found. Install Conda or initialize it for bash first." >&2
  exit 1
fi
conda activate "${CONDA_ENV_NAME:-agentscope}"

export OPENCLAW_IMAGE="${OPENCLAW_IMAGE:-openclaw-baseline:2026.6.11-srcsnap}"
export OPENCLAW_COMPOSE_PROJECT="${OPENCLAW_SCRIPT_COMPOSE_PROJECT:-openclaw-eval-gpqa}"
export OPENCLAW_GATEWAY_PORT="${OPENCLAW_SCRIPT_GATEWAY_PORT:-18802}"
export OPENCLAW_EVAL_STATE_DIR="${OPENCLAW_SCRIPT_STATE_DIR:-$PROJECT_ROOT/openclaw_evalscope_cli/.openclaw-eval/parallel/gpqa/state}"
export OPENCLAW_EVAL_SECRET_DIR="${OPENCLAW_SCRIPT_SECRET_DIR:-$PROJECT_ROOT/openclaw_evalscope_cli/.openclaw-eval/parallel/gpqa/secrets}"
export OPENCLAW_AUTO_UP=false

export EVALSCOPE_DATASETS=""
export EVALSCOPE_TASK_CONFIG=""
export EVALSCOPE_WORK_DIR=""
export EVALSCOPE_OUTPUT_ROOT="${EVALSCOPE_OUTPUT_ROOT:-$PROJECT_ROOT/outputs/parallel}"
export EVALSCOPE_MODEL_ID="${EVALSCOPE_MODEL_ID:-openclaw_baseline_deepseek_v32}"
export EVALSCOPE_DATASET=gpqa_diamond
export EVALSCOPE_DATASET_ARGS='{
  "gpqa_diamond": {
    "few_shot_num": 0
  }
}'
export EVALSCOPE_LIMIT="${EVALSCOPE_LIMIT:-5}"
export EVALSCOPE_JUDGE_STRATEGY="${EVALSCOPE_JUDGE_STRATEGY:-rule}"
export EVALSCOPE_BATCH_SIZE=1

mkdir -p "$OPENCLAW_EVAL_STATE_DIR" "$OPENCLAW_EVAL_SECRET_DIR"

docker compose \
  -f "$PROJECT_ROOT/openclaw_evalscope_cli/docker-compose.evalscope.yml" \
  -p "$OPENCLAW_COMPOSE_PROJECT" \
  up -d openclaw-gateway

for ((attempt = 1; attempt <= 90; attempt++)); do
  if curl -fs "http://127.0.0.1:${OPENCLAW_GATEWAY_PORT}/healthz" >/dev/null; then
    curl -fsS "http://127.0.0.1:${OPENCLAW_GATEWAY_PORT}/healthz"
    printf '\n'
    break
  fi
  if ((attempt == 90)); then
    docker compose \
      -f "$PROJECT_ROOT/openclaw_evalscope_cli/docker-compose.evalscope.yml" \
      -p "$OPENCLAW_COMPOSE_PROJECT" \
      logs --tail=100 openclaw-gateway
    echo "OpenClaw Gateway did not become healthy within 180 seconds." >&2
    exit 1
  fi
  sleep 2
done

python run.py
