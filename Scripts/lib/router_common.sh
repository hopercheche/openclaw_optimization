#!/usr/bin/env bash

# Shared runtime for the five Router benchmark entrypoints.
# Dataset-specific scripts set ROUTER_DATASET_* and EVALSCOPE_* before sourcing.

validate_router_models() {
  case "${OPENCLAW_ROUTER_VALIDATE_MODELS:-true}" in
    false|FALSE|0|no|NO) return 0 ;;
  esac

  local models_url="${EVALSCOPE_API_URL%/}/models"
  local catalog_file
  local http_status
  catalog_file="$(mktemp -t openclaw-router-models.XXXXXX)"

  if ! http_status="$(curl -sS -L --max-time 30 \
    -o "$catalog_file" \
    -w '%{http_code}' \
    -H "Authorization: Bearer ${EVALSCOPE_API_KEY}" \
    -H 'Accept: application/json' \
    "$models_url")"; then
    rm -f "$catalog_file"
    echo "Warning: could not query Router model catalog at $models_url; continuing without preflight." >&2
    return 0
  fi

  if [[ ! "$http_status" =~ ^2[0-9][0-9]$ ]]; then
    rm -f "$catalog_file"
    echo "Warning: Router model catalog returned HTTP $http_status at $models_url; continuing without preflight." >&2
    return 0
  fi

  if ! EVALSCOPE_ROUTER_MODEL_ROUTES="$EVALSCOPE_ROUTER_MODEL_ROUTES" \
    EVALSCOPE_API_URL="$EVALSCOPE_API_URL" \
    ROUTER_MODEL_CATALOG_FILE="$catalog_file" \
    python - <<'PY'
import json
import os
import sys

catalog_path = os.environ["ROUTER_MODEL_CATALOG_FILE"]
base_url = os.environ["EVALSCOPE_API_URL"].rstrip("/")

try:
    with open(catalog_path, encoding="utf-8") as file:
        payload = json.load(file)
    available = {
        str(model["id"])
        for model in payload.get("data", [])
        if isinstance(model, dict) and model.get("id")
    }
except (OSError, TypeError, ValueError) as exc:
    print(f"Warning: could not parse Router model catalog: {exc}; continuing without preflight.", file=sys.stderr)
    raise SystemExit(0)

if not available:
    print("Warning: Router model catalog did not contain model IDs; continuing without preflight.", file=sys.stderr)
    raise SystemExit(0)

routes = json.loads(os.environ["EVALSCOPE_ROUTER_MODEL_ROUTES"])
required = {
    str(route.get("model_id") or route_name)
    for route_name, route in routes.items()
    if isinstance(route, dict)
    and str(route.get("api_url", base_url)).rstrip("/") == base_url
    and route.get("api_key_env", "EVALSCOPE_API_KEY") == "EVALSCOPE_API_KEY"
}
missing = sorted(required - available)
if missing:
    print("Router model preflight failed: upstream endpoint does not advertise the configured model(s).", file=sys.stderr)
    print(f"Endpoint: {base_url}", file=sys.stderr)
    print(f"Missing: {', '.join(missing)}", file=sys.stderr)
    print(f"Available: {', '.join(sorted(available))}", file=sys.stderr)
    raise SystemExit(1)

print(f"Router model preflight: OK ({', '.join(sorted(required))})")
PY
  then
    rm -f "$catalog_file"
    return 1
  fi

  rm -f "$catalog_file"
}

run_router_eval() {
  : "${ROUTER_DATASET_SLUG:?ROUTER_DATASET_SLUG is required}"
  : "${ROUTER_GATEWAY_PORT:?ROUTER_GATEWAY_PORT is required}"
  : "${EVALSCOPE_DATASET:?EVALSCOPE_DATASET is required}"
  : "${EVALSCOPE_DATASET_ARGS:?EVALSCOPE_DATASET_ARGS is required}"

  local project_root="$1"
  local run_id="${OPENCLAW_ROUTER_RUN_ID:-$(date +%Y%m%d-%H%M%S)-$$}"
  local runtime_root="${OPENCLAW_ROUTER_LOCAL_STATE_ROOT:-/tmp/openclaw-eval/${USER:-user}/router}"
  local run_root="${runtime_root}/${ROUTER_DATASET_SLUG}/${run_id}"
  local lock_root="${runtime_root}/locks"
  local lock_file="${lock_root}/${ROUTER_DATASET_SLUG}.lock"
  local compose_base="${project_root}/openclaw_evalscope_cli/docker-compose.evalscope.yml"
  local compose_router="${project_root}/openclaw_evalscope_cli/docker-compose.router.yml"

  mkdir -p "$lock_root"
  if ! command -v flock >/dev/null 2>&1; then
    echo "flock is required to prevent duplicate Router runs." >&2
    return 1
  fi
  exec 9>"$lock_file"
  if ! flock -n 9; then
    echo "A Router evaluation for ${ROUTER_DATASET_SLUG} is already running." >&2
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

  export OPENCLAW_ROUTER_ENABLED=true
  export OPENCLAW_ROUTER_GATEWAY_IMAGE="${OPENCLAW_ROUTER_GATEWAY_IMAGE:-openclaw-router-gateway:2026.6.11-overlay}"
  export OPENCLAW_ROUTER_API_IMAGE="${OPENCLAW_ROUTER_API_IMAGE:-openclaw-router-api:2026.6.11}"
  export OPENCLAW_ROUTER_EMBEDDING_MODE="${OPENCLAW_ROUTER_EMBEDDING_MODE:-hash}"
  export OPENCLAW_ROUTER_STRICT=true
  export OPENCLAW_ROUTER_COLLECT_METRICS=true
  export OPENCLAW_ROUTER_CONFIDENCE_THRESHOLD="${OPENCLAW_ROUTER_CONFIDENCE_THRESHOLD:-0.5}"

  export OPENCLAW_IMAGE="${OPENCLAW_IMAGE:-openclaw-baseline:2026.6.11-srcsnap}"
  export OPENCLAW_COMPOSE_PROJECT="openclaw-router-${ROUTER_DATASET_SLUG}-${run_id}"
  export OPENCLAW_GATEWAY_PORT="$ROUTER_GATEWAY_PORT"
  export OPENCLAW_EVAL_STATE_DIR="${run_root}/state"
  export OPENCLAW_EVAL_SECRET_DIR="${run_root}/secrets"
  export OPENCLAW_AUTO_UP=false
  unset OPENCLAW_COMPOSE_FILES

  export EVALSCOPE_MODEL="${EVALSCOPE_MODEL:-qwen3.7-max}"
  export EVALSCOPE_EVAL_TYPE="${EVALSCOPE_EVAL_TYPE:-openai_api}"
  export EVALSCOPE_API_URL="${EVALSCOPE_API_URL:-https://opencode.ai/zen/go/v1}"
  export EVALSCOPE_API_KEY="${EVALSCOPE_API_KEY:-sk-BR7R7DMrTgtxBr4Q7hYBXU6g8rIDPnZPuUC5m7tISdgH3qhMFKWPep5TvVVFBqZl}"
  export EVALSCOPE_MODEL_ID="${OPENCLAW_ROUTER_MODEL_ID:-openclaw_router_${EVALSCOPE_MODEL}}"
  export EVALSCOPE_BATCH_SIZE=1
  export EVALSCOPE_TEMPERATURE="${EVALSCOPE_TEMPERATURE:-0.0}"
  export EVALSCOPE_MAX_TOKENS="${EVALSCOPE_MAX_TOKENS:-2048}"
  export EVALSCOPE_STREAM=false
  export EVALSCOPE_COST_CURRENCY="${EVALSCOPE_COST_CURRENCY:-USD}"
  export EVALSCOPE_DATASET_DIR="${OPENCLAW_ROUTER_DATASET_DIR:-/home/featurize/data}"
  export EVALSCOPE_DATASET_HUB="${EVALSCOPE_DATASET_HUB:-modelscope}"
  export MODELSCOPE_CACHE="${OPENCLAW_ROUTER_MODELSCOPE_CACHE:-/home/featurize/data/modelscope-cache}"
  export HF_HOME="${OPENCLAW_ROUTER_HF_HOME:-/home/featurize/data/huggingface-cache}"
  export EVALSCOPE_OUTPUT_ROOT="${OPENCLAW_ROUTER_OUTPUT_ROOT:-${project_root}/outputs/router}"
  export EVALSCOPE_DATASETS=""
  export EVALSCOPE_TASK_CONFIG=""
  export EVALSCOPE_WORK_DIR=""

  export EVALSCOPE_JUDGE_MODEL="${EVALSCOPE_JUDGE_MODEL:-$EVALSCOPE_MODEL}"
  export EVALSCOPE_JUDGE_EVAL_TYPE="${EVALSCOPE_JUDGE_EVAL_TYPE:-$EVALSCOPE_EVAL_TYPE}"
  export EVALSCOPE_JUDGE_API_URL="${EVALSCOPE_JUDGE_API_URL:-$EVALSCOPE_API_URL}"
  export EVALSCOPE_JUDGE_API_KEY="${EVALSCOPE_JUDGE_API_KEY:-$EVALSCOPE_API_KEY}"

  local small_model="${OPENCLAW_ROUTER_SMALL_MODEL:-qwen3.6-plus}"
  local mid_model="${OPENCLAW_ROUTER_MID_MODEL:-qwen3.7-plus}"
  local large_model="${OPENCLAW_ROUTER_LARGE_MODEL:-qwen3.7-max}"
  # OpenCode Go public prices per 1M tokens, checked 2026-07-15.
  local small_input_price="${OPENCLAW_ROUTER_SMALL_INPUT_PRICE_PER_MILLION:-0.50}"
  local small_output_price="${OPENCLAW_ROUTER_SMALL_OUTPUT_PRICE_PER_MILLION:-3.00}"
  local small_cache_read_price="${OPENCLAW_ROUTER_SMALL_CACHE_READ_PRICE_PER_MILLION:-0.05}"
  local small_cache_write_price="${OPENCLAW_ROUTER_SMALL_CACHE_WRITE_PRICE_PER_MILLION:-0.625}"
  local mid_input_price="${OPENCLAW_ROUTER_MID_INPUT_PRICE_PER_MILLION:-0.40}"
  local mid_output_price="${OPENCLAW_ROUTER_MID_OUTPUT_PRICE_PER_MILLION:-1.60}"
  local mid_cache_read_price="${OPENCLAW_ROUTER_MID_CACHE_READ_PRICE_PER_MILLION:-0.04}"
  local mid_cache_write_price="${OPENCLAW_ROUTER_MID_CACHE_WRITE_PRICE_PER_MILLION:-0.50}"
  local large_input_price="${OPENCLAW_ROUTER_LARGE_INPUT_PRICE_PER_MILLION:-2.50}"
  local large_output_price="${OPENCLAW_ROUTER_LARGE_OUTPUT_PRICE_PER_MILLION:-7.50}"
  local large_cache_read_price="${OPENCLAW_ROUTER_LARGE_CACHE_READ_PRICE_PER_MILLION:-0.50}"
  local large_cache_write_price="${OPENCLAW_ROUTER_LARGE_CACHE_WRITE_PRICE_PER_MILLION:-3.125}"

  if [[ -z "${OPENCLAW_ROUTER_TIERS:-}" ]]; then
    export OPENCLAW_ROUTER_TIERS
    OPENCLAW_ROUTER_TIERS="$(cat <<JSON
{"small":"${small_model}","mid":"${mid_model}","large":"${large_model}"}
JSON
)"
  fi

  if [[ -z "${EVALSCOPE_ROUTER_MODEL_ROUTES:-}" ]]; then
    export EVALSCOPE_ROUTER_MODEL_ROUTES
    EVALSCOPE_ROUTER_MODEL_ROUTES="$(cat <<JSON
{
  "${small_model}": {
    "model_id": "${small_model}",
    "eval_type": "${EVALSCOPE_EVAL_TYPE}",
    "api_url": "${EVALSCOPE_API_URL}",
    "api_key_env": "EVALSCOPE_API_KEY",
    "generation_config": {"temperature": ${EVALSCOPE_TEMPERATURE}, "max_tokens": ${EVALSCOPE_MAX_TOKENS}},
    "openclaw_model": {
      "reasoning": false,
      "contextWindow": 131072,
      "maxTokens": ${EVALSCOPE_MAX_TOKENS},
      "cost": {
        "input": ${small_input_price},
        "output": ${small_output_price},
        "cacheRead": ${small_cache_read_price},
        "cacheWrite": ${small_cache_write_price}
      }
    }
  },
  "${mid_model}": {
    "model_id": "${mid_model}",
    "eval_type": "${EVALSCOPE_EVAL_TYPE}",
    "api_url": "${EVALSCOPE_API_URL}",
    "api_key_env": "EVALSCOPE_API_KEY",
    "generation_config": {"temperature": ${EVALSCOPE_TEMPERATURE}, "max_tokens": ${EVALSCOPE_MAX_TOKENS}},
    "openclaw_model": {
      "reasoning": true,
      "contextWindow": 131072,
      "maxTokens": ${EVALSCOPE_MAX_TOKENS},
      "cost": {
        "input": ${mid_input_price},
        "output": ${mid_output_price},
        "cacheRead": ${mid_cache_read_price},
        "cacheWrite": ${mid_cache_write_price}
      }
    }
  },
  "${large_model}": {
    "model_id": "${large_model}",
    "eval_type": "${EVALSCOPE_EVAL_TYPE}",
    "api_url": "${EVALSCOPE_API_URL}",
    "api_key_env": "EVALSCOPE_API_KEY",
    "generation_config": {"temperature": ${EVALSCOPE_TEMPERATURE}, "max_tokens": ${EVALSCOPE_MAX_TOKENS}},
    "openclaw_model": {
      "reasoning": true,
      "contextWindow": 131072,
      "maxTokens": ${EVALSCOPE_MAX_TOKENS},
      "cost": {
        "input": ${large_input_price},
        "output": ${large_output_price},
        "cacheRead": ${large_cache_read_price},
        "cacheWrite": ${large_cache_write_price}
      }
    }
  }
}
JSON
)"
  fi

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

  validate_router_models

  docker image inspect "$OPENCLAW_ROUTER_GATEWAY_IMAGE" >/dev/null
  docker image inspect "$OPENCLAW_ROUTER_API_IMAGE" >/dev/null

  local -a compose_cmd=(
    docker compose
    -f "$compose_base"
    -f "$compose_router"
    -p "$OPENCLAW_COMPOSE_PROJECT"
  )

  router_cleanup() {
    local status="${1:-$?}"
    trap - EXIT INT TERM
    if ((status != 0)); then
      "${compose_cmd[@]}" logs --tail=200 openclaw-gateway openclaw-router-api >&2 || true
    fi
    if [[ "${OPENCLAW_ROUTER_KEEP_CONTAINERS:-false}" != "true" ]]; then
      "${compose_cmd[@]}" down --remove-orphans >/dev/null 2>&1 || true
    fi
    exit "$status"
  }
  trap 'router_cleanup $?' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  printf 'Router dataset: %s\n' "$EVALSCOPE_DATASET"
  printf 'Compose project: %s\n' "$OPENCLAW_COMPOSE_PROJECT"
  printf 'Gateway port: %s\n' "$OPENCLAW_GATEWAY_PORT"
  printf 'Local OpenClaw state: %s\n' "$OPENCLAW_EVAL_STATE_DIR"
  printf 'EvalScope dataset directory: %s\n' "$EVALSCOPE_DATASET_DIR"
  printf 'EvalScope output root: %s\n' "$EVALSCOPE_OUTPUT_ROOT"
  printf 'Router tiers: small=%s mid=%s large=%s\n' "$small_model" "$mid_model" "$large_model"
  printf 'Router pricing currency: %s (per 1M tokens)\n' "$EVALSCOPE_COST_CURRENCY"

  "${compose_cmd[@]}" up -d openclaw-gateway

  local attempt
  for ((attempt = 1; attempt <= 90; attempt++)); do
    if curl -fs "http://127.0.0.1:${OPENCLAW_GATEWAY_PORT}/healthz" >/dev/null; then
      curl -fsS "http://127.0.0.1:${OPENCLAW_GATEWAY_PORT}/healthz"
      printf '\n'
      break
    fi
    if ((attempt == 90)); then
      "${compose_cmd[@]}" logs --tail=200 openclaw-gateway openclaw-router-api >&2
      echo "OpenClaw Router Gateway did not become healthy within 180 seconds." >&2
      return 1
    fi
    sleep 2
  done

  python run.py
  router_cleanup 0
}
