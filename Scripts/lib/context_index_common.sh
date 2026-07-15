#!/usr/bin/env bash

# Shared runtime for the five Context Index benchmark entrypoints.
# Dataset-specific scripts set CONTEXT_INDEX_DATASET_* and EVALSCOPE_* first.

context_index_bool_json() {
  case "$1" in
    true|TRUE|1|yes|YES|on|ON) printf 'true' ;;
    false|FALSE|0|no|NO|off|OFF) printf 'false' ;;
    *) echo "Expected a boolean value, got: $1" >&2; return 1 ;;
  esac
}

run_context_index_eval() {
  : "${CONTEXT_INDEX_DATASET_SLUG:?CONTEXT_INDEX_DATASET_SLUG is required}"
  : "${CONTEXT_INDEX_GATEWAY_PORT:?CONTEXT_INDEX_GATEWAY_PORT is required}"
  : "${EVALSCOPE_DATASET:?EVALSCOPE_DATASET is required}"
  : "${EVALSCOPE_DATASET_ARGS:?EVALSCOPE_DATASET_ARGS is required}"

  local project_root="$1"
  local run_id="${OPENCLAW_CONTEXT_INDEX_RUN_ID:-$(date +%Y%m%d-%H%M%S)-$$}"
  local runtime_root="${OPENCLAW_CONTEXT_INDEX_LOCAL_STATE_ROOT:-/tmp/openclaw-eval/${USER:-user}/context-index}"
  local run_root="${runtime_root}/${CONTEXT_INDEX_DATASET_SLUG}/${run_id}"
  local lock_root="${runtime_root}/locks"
  local lock_file="${lock_root}/${CONTEXT_INDEX_DATASET_SLUG}.lock"
  local compose_file="${project_root}/openclaw_evalscope_cli/docker-compose.evalscope.yml"

  mkdir -p "$lock_root"
  if ! command -v flock >/dev/null 2>&1; then
    echo "flock is required to prevent duplicate Context Index runs." >&2
    return 1
  fi
  exec 9>"$lock_file"
  if ! flock -n 9; then
    echo "A Context Index evaluation for ${CONTEXT_INDEX_DATASET_SLUG} is already running." >&2
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

  export OPENCLAW_CONTEXT_INDEX_ENABLED=true
  export OPENCLAW_CONTEXT_INDEX_IMAGE="${OPENCLAW_CONTEXT_INDEX_IMAGE:-openclaw-context-index:2026.6.11-overlay}"
  export OPENCLAW_CONTEXT_INDEX_PLUGIN_ID="${OPENCLAW_CONTEXT_INDEX_PLUGIN_ID:-context-index}"
  export OPENCLAW_CONTEXT_INDEX_PLUGIN_PATH="${OPENCLAW_CONTEXT_INDEX_PLUGIN_PATH:-/opt/openclaw-plugins/context-index}"
  export OPENCLAW_CONTEXT_INDEX_COLLECT_AUDIT="${OPENCLAW_CONTEXT_INDEX_COLLECT_AUDIT:-true}"
  export OPENCLAW_CONTEXT_INDEX_AUDIT_LIMIT="${OPENCLAW_CONTEXT_INDEX_AUDIT_LIMIT:-2000}"
  export OPENCLAW_CONTEXT_INDEX_RESET_PER_SAMPLE="${OPENCLAW_CONTEXT_INDEX_RESET_PER_SAMPLE:-true}"

  if [[ -z "${OPENCLAW_CONTEXT_INDEX_CONFIG:-}" ]]; then
    local audit_enabled
    audit_enabled="$(context_index_bool_json "${OPENCLAW_CONTEXT_INDEX_AUDIT_ENABLED:-true}")"
    export OPENCLAW_CONTEXT_INDEX_CONFIG
    OPENCLAW_CONTEXT_INDEX_CONFIG="$(cat <<JSON
{
  "mode": "${OPENCLAW_CONTEXT_INDEX_MODE:-progressive}",
  "defaultProjectId": "${OPENCLAW_CONTEXT_INDEX_PROJECT_ID:-evalscope-${CONTEXT_INDEX_DATASET_SLUG}}",
  "recentMessageLimit": ${OPENCLAW_CONTEXT_INDEX_RECENT_MESSAGE_LIMIT:-8},
  "maxSnippetChars": ${OPENCLAW_CONTEXT_INDEX_MAX_SNIPPET_CHARS:-900},
  "retrieval": {
    "topK": ${OPENCLAW_CONTEXT_INDEX_TOP_K:-8},
    "candidateK": ${OPENCLAW_CONTEXT_INDEX_CANDIDATE_K:-80},
    "halfLifeDays": ${OPENCLAW_CONTEXT_INDEX_HALF_LIFE_DAYS:-30}
  },
  "scoring": {
    "keywordWeight": ${OPENCLAW_CONTEXT_INDEX_KEYWORD_WEIGHT:-0.35},
    "scopeWeight": ${OPENCLAW_CONTEXT_INDEX_SCOPE_WEIGHT:-0.20},
    "stageWeight": ${OPENCLAW_CONTEXT_INDEX_STAGE_WEIGHT:-0.15},
    "recencyWeight": ${OPENCLAW_CONTEXT_INDEX_RECENCY_WEIGHT:-0.15},
    "importanceWeight": ${OPENCLAW_CONTEXT_INDEX_IMPORTANCE_WEIGHT:-0.10},
    "validityWeight": ${OPENCLAW_CONTEXT_INDEX_VALIDITY_WEIGHT:-0.05}
  },
  "audit": {"enabled": ${audit_enabled}}
}
JSON
)"
  fi

  export OPENCLAW_IMAGE="$OPENCLAW_CONTEXT_INDEX_IMAGE"
  export OPENCLAW_COMPOSE_PROJECT="openclaw-context-index-${CONTEXT_INDEX_DATASET_SLUG}-${run_id}"
  export OPENCLAW_GATEWAY_PORT="$CONTEXT_INDEX_GATEWAY_PORT"
  export OPENCLAW_EVAL_STATE_DIR="${run_root}/state"
  export OPENCLAW_EVAL_SECRET_DIR="${run_root}/secrets"
  export OPENCLAW_AUTO_UP=false
  export OPENCLAW_ROUTER_ENABLED=false
  unset OPENCLAW_COMPOSE_FILES

  export EVALSCOPE_MODEL="${EVALSCOPE_MODEL:-qwen3.7-max}"
  export EVALSCOPE_EVAL_TYPE="${EVALSCOPE_EVAL_TYPE:-openai_api}"
  export EVALSCOPE_API_URL="${EVALSCOPE_API_URL:-https://opencode.ai/zen/go/v1}"
  export EVALSCOPE_API_KEY="${EVALSCOPE_API_KEY:-sk-BR7R7DMrTgtxBr4Q7hYBXU6g8rIDPnZPuUC5m7tISdgH3qhMFKWPep5TvVVFBqZl}"
  export EVALSCOPE_MODEL_ID="${OPENCLAW_CONTEXT_INDEX_MODEL_ID:-openclaw_context_index_${EVALSCOPE_MODEL}}"
  export EVALSCOPE_BATCH_SIZE=1
  export EVALSCOPE_TEMPERATURE="${EVALSCOPE_TEMPERATURE:-0.0}"
  export EVALSCOPE_MAX_TOKENS="${EVALSCOPE_MAX_TOKENS:-2048}"
  export EVALSCOPE_STREAM=false
  export EVALSCOPE_COST_CURRENCY="${EVALSCOPE_COST_CURRENCY:-USD}"
  export EVALSCOPE_INPUT_PRICE_PER_MILLION="${EVALSCOPE_INPUT_PRICE_PER_MILLION:-2.50}"
  export EVALSCOPE_OUTPUT_PRICE_PER_MILLION="${EVALSCOPE_OUTPUT_PRICE_PER_MILLION:-7.50}"
  export EVALSCOPE_CACHED_INPUT_PRICE_PER_MILLION="${EVALSCOPE_CACHED_INPUT_PRICE_PER_MILLION:-0.50}"
  export EVALSCOPE_DATASET_DIR="${OPENCLAW_CONTEXT_INDEX_DATASET_DIR:-/home/featurize/data}"
  export EVALSCOPE_DATASET_HUB="${EVALSCOPE_DATASET_HUB:-modelscope}"
  export MODELSCOPE_CACHE="${OPENCLAW_CONTEXT_INDEX_MODELSCOPE_CACHE:-/home/featurize/data/modelscope-cache}"
  export HF_HOME="${OPENCLAW_CONTEXT_INDEX_HF_HOME:-/home/featurize/data/huggingface-cache}"
  export EVALSCOPE_OUTPUT_ROOT="${OPENCLAW_CONTEXT_INDEX_OUTPUT_ROOT:-${project_root}/outputs/context-index}"
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

  docker image inspect "$OPENCLAW_CONTEXT_INDEX_IMAGE" >/dev/null

  local -a compose_cmd=(
    docker compose
    -f "$compose_file"
    -p "$OPENCLAW_COMPOSE_PROJECT"
  )

  context_index_cleanup() {
    local status="${1:-$?}"
    trap - EXIT INT TERM
    if ((status != 0)); then
      "${compose_cmd[@]}" logs --tail=200 openclaw-gateway >&2 || true
    fi
    if [[ "${OPENCLAW_CONTEXT_INDEX_KEEP_CONTAINERS:-false}" != "true" ]]; then
      "${compose_cmd[@]}" down --remove-orphans >/dev/null 2>&1 || true
    fi
    exit "$status"
  }
  trap 'context_index_cleanup $?' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  printf 'Context Index dataset: %s\n' "$EVALSCOPE_DATASET"
  printf 'Compose project: %s\n' "$OPENCLAW_COMPOSE_PROJECT"
  printf 'Gateway image: %s\n' "$OPENCLAW_CONTEXT_INDEX_IMAGE"
  printf 'Gateway port: %s\n' "$OPENCLAW_GATEWAY_PORT"
  printf 'Local OpenClaw state: %s\n' "$OPENCLAW_EVAL_STATE_DIR"
  printf 'EvalScope dataset directory: %s\n' "$EVALSCOPE_DATASET_DIR"
  printf 'EvalScope output root: %s\n' "$EVALSCOPE_OUTPUT_ROOT"
  printf 'Context Index mode: %s; reset per sample: %s\n' \
    "${OPENCLAW_CONTEXT_INDEX_MODE:-progressive}" "$OPENCLAW_CONTEXT_INDEX_RESET_PER_SAMPLE"

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
      echo "OpenClaw Context Index Gateway did not become healthy within 180 seconds." >&2
      return 1
    fi
    sleep 2
  done

  python run.py
  context_index_cleanup 0
}
