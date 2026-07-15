#!/usr/bin/env bash

# Shared runtime for the five Task Compass Planner benchmark entrypoints.
# Dataset-specific scripts set PLANNER_DATASET_* and EVALSCOPE_* first.

planner_bool_json() {
  case "$1" in
    true|TRUE|1|yes|YES|on|ON) printf 'true' ;;
    false|FALSE|0|no|NO|off|OFF) printf 'false' ;;
    *) echo "Expected a boolean value, got: $1" >&2; return 1 ;;
  esac
}

run_planner_eval() {
  : "${PLANNER_DATASET_SLUG:?PLANNER_DATASET_SLUG is required}"
  : "${PLANNER_GATEWAY_PORT:?PLANNER_GATEWAY_PORT is required}"
  : "${EVALSCOPE_DATASET:?EVALSCOPE_DATASET is required}"
  : "${EVALSCOPE_DATASET_ARGS:?EVALSCOPE_DATASET_ARGS is required}"

  local project_root="$1"
  local run_id="${OPENCLAW_PLANNER_RUN_ID:-$(date +%Y%m%d-%H%M%S)-$$}"
  local runtime_root="${OPENCLAW_PLANNER_LOCAL_STATE_ROOT:-/tmp/openclaw-eval/${USER:-user}/planner}"
  local run_root="${runtime_root}/${PLANNER_DATASET_SLUG}/${run_id}"
  local lock_root="${runtime_root}/locks"
  local lock_file="${lock_root}/${PLANNER_DATASET_SLUG}.lock"
  local compose_file="${project_root}/openclaw_evalscope_cli/docker-compose.evalscope.yml"

  mkdir -p "$lock_root"
  if ! command -v flock >/dev/null 2>&1; then
    echo "flock is required to prevent duplicate Planner runs." >&2
    return 1
  fi
  exec 9>"$lock_file"
  if ! flock -n 9; then
    echo "A Planner evaluation for ${PLANNER_DATASET_SLUG} is already running." >&2
    return 1
  fi

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
    return 1
  fi
  conda activate "${CONDA_ENV_NAME:-agentscope}"

  export OPENCLAW_PLANNER_ENABLED=true
  export OPENCLAW_PLANNER_IMAGE="${OPENCLAW_PLANNER_IMAGE:-openclaw-planner:2026.6.11-overlay}"
  export OPENCLAW_PLANNER_PLUGIN_ID="${OPENCLAW_PLANNER_PLUGIN_ID:-task-compass}"
  export OPENCLAW_PLANNER_PLUGIN_PATH="${OPENCLAW_PLANNER_PLUGIN_PATH:-/opt/openclaw-plugins/task-compass}"
  export OPENCLAW_PLANNER_COLLECT_DECISION="${OPENCLAW_PLANNER_COLLECT_DECISION:-true}"

  if [[ -z "${OPENCLAW_PLANNER_CONFIG:-}" ]]; then
    local planner_enabled
    planner_enabled="$(planner_bool_json "${OPENCLAW_PLANNER_PLUGIN_ENABLED:-true}")"
    export OPENCLAW_PLANNER_CONFIG
    OPENCLAW_PLANNER_CONFIG="$(cat <<JSON
{
  "enabled": ${planner_enabled},
  "pythonBin": "${OPENCLAW_PLANNER_PYTHON_BIN:-python3}",
  "timeoutMs": ${OPENCLAW_PLANNER_TIMEOUT_MS:-1500},
  "maxPromptChars": ${OPENCLAW_PLANNER_MAX_PROMPT_CHARS:-12000}
}
JSON
)"
  fi

  export OPENCLAW_IMAGE="$OPENCLAW_PLANNER_IMAGE"
  export OPENCLAW_COMPOSE_PROJECT="openclaw-planner-${PLANNER_DATASET_SLUG}-${run_id}"
  export OPENCLAW_GATEWAY_PORT="$PLANNER_GATEWAY_PORT"
  export OPENCLAW_EVAL_STATE_DIR="${run_root}/state"
  export OPENCLAW_EVAL_SECRET_DIR="${run_root}/secrets"
  export OPENCLAW_AUTO_UP=false
  export OPENCLAW_ROUTER_ENABLED=false
  export OPENCLAW_CONTEXT_INDEX_ENABLED=false
  unset OPENCLAW_COMPOSE_FILES

  export EVALSCOPE_MODEL="${EVALSCOPE_MODEL:-qwen3.7-max}"
  export EVALSCOPE_EVAL_TYPE="${EVALSCOPE_EVAL_TYPE:-openai_api}"
  export EVALSCOPE_API_URL="${EVALSCOPE_API_URL:-https://opencode.ai/zen/go/v1}"
  export EVALSCOPE_API_KEY="${EVALSCOPE_API_KEY:-sk-BR7R7DMrTgtxBr4Q7hYBXU6g8rIDPnZPuUC5m7tISdgH3qhMFKWPep5TvVVFBqZl}"
  export EVALSCOPE_MODEL_ID="${OPENCLAW_PLANNER_MODEL_ID:-openclaw_planner_${EVALSCOPE_MODEL}}"
  export EVALSCOPE_BATCH_SIZE=1
  export EVALSCOPE_TEMPERATURE="${EVALSCOPE_TEMPERATURE:-0.0}"
  export EVALSCOPE_MAX_TOKENS="${EVALSCOPE_MAX_TOKENS:-2048}"
  export EVALSCOPE_STREAM=false
  export EVALSCOPE_COST_CURRENCY="${EVALSCOPE_COST_CURRENCY:-USD}"
  export EVALSCOPE_INPUT_PRICE_PER_MILLION="${EVALSCOPE_INPUT_PRICE_PER_MILLION:-2.50}"
  export EVALSCOPE_OUTPUT_PRICE_PER_MILLION="${EVALSCOPE_OUTPUT_PRICE_PER_MILLION:-7.50}"
  export EVALSCOPE_CACHED_INPUT_PRICE_PER_MILLION="${EVALSCOPE_CACHED_INPUT_PRICE_PER_MILLION:-0.50}"
  export EVALSCOPE_DATASET_DIR="${OPENCLAW_PLANNER_DATASET_DIR:-/home/featurize/data}"
  export EVALSCOPE_DATASET_HUB="${EVALSCOPE_DATASET_HUB:-modelscope}"
  export MODELSCOPE_CACHE="${OPENCLAW_PLANNER_MODELSCOPE_CACHE:-/home/featurize/data/modelscope-cache}"
  export HF_HOME="${OPENCLAW_PLANNER_HF_HOME:-/home/featurize/data/huggingface-cache}"
  export EVALSCOPE_OUTPUT_ROOT="${OPENCLAW_PLANNER_OUTPUT_ROOT:-${project_root}/outputs/planner}"
  export EVALSCOPE_DATASETS=""
  export EVALSCOPE_TASK_CONFIG=""
  export EVALSCOPE_WORK_DIR=""

  export EVALSCOPE_JUDGE_MODEL="${EVALSCOPE_JUDGE_MODEL:-$EVALSCOPE_MODEL}"
  export EVALSCOPE_JUDGE_EVAL_TYPE="${EVALSCOPE_JUDGE_EVAL_TYPE:-$EVALSCOPE_EVAL_TYPE}"
  export EVALSCOPE_JUDGE_API_URL="${EVALSCOPE_JUDGE_API_URL:-$EVALSCOPE_API_URL}"
  export EVALSCOPE_JUDGE_API_KEY="${EVALSCOPE_JUDGE_API_KEY:-$EVALSCOPE_API_KEY}"

  mkdir -p \
    "$OPENCLAW_EVAL_STATE_DIR" \
    "$OPENCLAW_EVAL_SECRET_DIR" \
    "$EVALSCOPE_DATASET_DIR" \
    "$MODELSCOPE_CACHE" \
    "$HF_HOME" \
    "$EVALSCOPE_OUTPUT_ROOT"
  chmod 700 "$OPENCLAW_EVAL_STATE_DIR" "$OPENCLAW_EVAL_SECRET_DIR"

  if [[ ! -w "$EVALSCOPE_DATASET_DIR" ]]; then
    echo "EvalScope dataset directory is not writable: $EVALSCOPE_DATASET_DIR" >&2
    return 1
  fi

  docker image inspect "$OPENCLAW_PLANNER_IMAGE" >/dev/null

  local -a compose_cmd=(
    docker compose
    -f "$compose_file"
    -p "$OPENCLAW_COMPOSE_PROJECT"
  )

  planner_cleanup() {
    local status="${1:-$?}"
    trap - EXIT INT TERM
    if ((status != 0)); then
      "${compose_cmd[@]}" logs --tail=200 openclaw-gateway >&2 || true
    fi
    if [[ "${OPENCLAW_PLANNER_KEEP_CONTAINERS:-false}" != "true" ]]; then
      "${compose_cmd[@]}" down --remove-orphans >/dev/null 2>&1 || true
    fi
    exit "$status"
  }
  trap 'planner_cleanup $?' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  printf 'Planner dataset: %s\n' "$EVALSCOPE_DATASET"
  printf 'Compose project: %s\n' "$OPENCLAW_COMPOSE_PROJECT"
  printf 'Gateway image: %s\n' "$OPENCLAW_PLANNER_IMAGE"
  printf 'Gateway port: %s\n' "$OPENCLAW_GATEWAY_PORT"
  printf 'Local OpenClaw state: %s\n' "$OPENCLAW_EVAL_STATE_DIR"
  printf 'EvalScope dataset directory: %s\n' "$EVALSCOPE_DATASET_DIR"
  printf 'EvalScope output root: %s\n' "$EVALSCOPE_OUTPUT_ROOT"

  "${compose_cmd[@]}" up -d openclaw-gateway

  local attempt
  for ((attempt = 1; attempt <= 90; attempt++)); do
    if curl -fs "http://127.0.0.1:${OPENCLAW_GATEWAY_PORT}/healthz" >/dev/null; then
      curl -fsS "http://127.0.0.1:${OPENCLAW_GATEWAY_PORT}/healthz"
      printf '\n'
      break
    fi
    if ((attempt == 90)); then
      "${compose_cmd[@]}" logs --tail=200 openclaw-gateway >&2
      echo "OpenClaw Planner Gateway did not become healthy within 180 seconds." >&2
      return 1
    fi
    sleep 2
  done

  python run.py
  planner_cleanup 0
}
