#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_NAME="${OPENCLAW_DOCKER_IMAGE:-openclaw:secure-local}"
CONTAINER_NAME="${OPENCLAW_DOCKER_CONTAINER:-openclaw-secure}"
GATEWAY_NAME="${OPENCLAW_DOCKER_GATEWAY:-${CONTAINER_NAME}-gateway}"
API_PROXY_NAME="${OPENCLAW_DOCKER_API_PROXY:-${CONTAINER_NAME}-api-proxy}"
INTERNAL_NETWORK="${OPENCLAW_DOCKER_INTERNAL_NETWORK:-openclaw-internal}"
HOST_PORT="${OPENCLAW_DOCKER_PORT:-8788}"
API_ENV_FILE="${OPENCLAW_API_ENV_FILE:-$ROOT_DIR/deploy/openclaw-api.env}"
APP_UID="${OPENCLAW_DOCKER_UID:-$(id -u)}"
APP_GID="${OPENCLAW_DOCKER_GID:-$(id -g)}"

ALLOWED_API_ENV_KEYS=(
  DEEPSEEK_API_KEY
  DEEPSEEK_BASE_URL
  OPENCLAW_DEEPSEEK_MODEL
  OPENAI_API_KEY
  OPENAI_BASE_URL
  OPENCLAW_OPENAI_BASE_URL
  OPENCLAW_OPENAI_MODEL
  DASHSCOPE_API_KEY
  DASHSCOPE_BASE_URL
  OPENCLAW_DASHSCOPE_MODEL
  OPENCLAW_MODEL_TIMEOUT_SECONDS
  OPENCLAW_MODEL_MAX_TOKENS
)

ALLOWED_NON_SECRET_ENV_KEYS=(
  OPENCLAW_PLANNER_STRATEGY
  OPENCLAW_MODEL_PLANNER_POLICY
  OPENCLAW_PLANNER_PROFILE_MODEL
  OPENCLAW_TERMINAL_PLANNER_PROFILE_MODEL
)

usage() {
  cat <<'USAGE'
Usage:
  scripts/openclaw_secure_docker.sh build
  scripts/openclaw_secure_docker.sh run
  scripts/openclaw_secure_docker.sh run-api
  scripts/openclaw_secure_docker.sh stop
  scripts/openclaw_secure_docker.sh logs
  scripts/openclaw_secure_docker.sh status

Modes:
  run      Uses an internal Docker network. Host can reach 127.0.0.1:8788,
           through a no-secret TCP gateway sidecar, while the OpenClaw app
           container has no external egress.
  run-api  Keeps the OpenClaw app on an internal network and routes HTTPS model
           API calls through a no-secret allowlist proxy sidecar. Only
           allowlisted API/provider variables are injected into the app.
USAGE
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "docker command not found" >&2
    exit 1
  fi
}

ensure_internal_network() {
  if docker network inspect "$INTERNAL_NETWORK" >/dev/null 2>&1; then
    return
  fi
  docker network create --internal "$INTERNAL_NETWORK" >/dev/null
}

build_image() {
  require_docker
  docker build \
    -f "$ROOT_DIR/Dockerfile.openclaw-secure" \
    -t "$IMAGE_NAME" \
    "$ROOT_DIR"
}

stop_container() {
  require_docker
  if docker ps -a --format '{{.Names}}' | grep -Fxq "$API_PROXY_NAME"; then
    docker rm -f "$API_PROXY_NAME" >/dev/null
  fi
  if docker ps -a --format '{{.Names}}' | grep -Fxq "$GATEWAY_NAME"; then
    docker rm -f "$GATEWAY_NAME" >/dev/null
  fi
  if docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
    docker rm -f "$CONTAINER_NAME" >/dev/null
  fi
}

env_key_allowed() {
  local key="$1"
  shift
  local allowed
  for allowed in "$@"; do
    if [[ "$key" == "$allowed" ]]; then
      return 0
    fi
  done
  return 1
}

append_env_from_file() {
  local -n _target_args="$1"
  local file="$2"
  local line key value
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    env_key_allowed "$key" "${ALLOWED_API_ENV_KEYS[@]}" || continue
    _target_args+=("-e" "$key=$value")
  done < "$file"
}

append_env_from_current() {
  local -n _target_args="$1"
  local key
  for key in "$@"; do
    if [[ -n "${!key:-}" ]]; then
      _target_args+=("-e" "$key=${!key}")
    fi
  done
}

env_file_value() {
  local wanted_key="$1"
  local line key value
  [[ -f "$API_ENV_FILE" ]] || return 1
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    [[ "$key" == "$wanted_key" ]] || continue
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
    printf '%s' "$value"
    return 0
  done < "$API_ENV_FILE"
  return 1
}

env_or_file_value() {
  local key value
  for key in "$@"; do
    if [[ -n "${!key:-}" ]]; then
      printf '%s' "${!key}"
      return 0
    fi
    if value="$(env_file_value "$key")" && [[ -n "$value" ]]; then
      printf '%s' "$value"
      return 0
    fi
  done
  return 1
}

has_env_or_file_value() {
  local value
  value="$(env_or_file_value "$@" || true)"
  [[ -n "$value" ]]
}

host_from_url() {
  local url="$1"
  local host
  url="${url%\"}"
  url="${url#\"}"
  url="${url%\'}"
  url="${url#\'}"
  if [[ "$url" == *"://"* ]]; then
    host="${url#*://}"
  else
    host="$url"
  fi
  host="${host%%/*}"
  host="${host#[}"
  host="${host%]}"
  host="${host%%:*}"
  printf '%s' "$host"
}

append_unique_host() {
  local -n _hosts="$1"
  local host="$2"
  local existing
  [[ -n "$host" ]] || return 0
  for existing in "${_hosts[@]}"; do
    [[ "$existing" == "$host" ]] && return 0
  done
  _hosts+=("$host")
}

append_host_from_url() {
  local target_array="$1"
  local url="$2"
  local host
  host="$(host_from_url "$url")"
  append_unique_host "$target_array" "$host"
}

collect_api_proxy_allow_hosts() {
  if [[ -n "${OPENCLAW_API_PROXY_ALLOW_HOSTS:-}" ]]; then
    printf '%s' "$OPENCLAW_API_PROXY_ALLOW_HOSTS"
    return 0
  fi

  local hosts=()
  local base_url
  if has_env_or_file_value DEEPSEEK_API_KEY; then
    base_url="$(env_or_file_value DEEPSEEK_BASE_URL || printf 'https://api.deepseek.com')"
    append_host_from_url hosts "$base_url"
  fi
  if has_env_or_file_value OPENAI_API_KEY; then
    base_url="$(env_or_file_value OPENAI_BASE_URL OPENCLAW_OPENAI_BASE_URL || printf 'https://api.openai.com/v1')"
    append_host_from_url hosts "$base_url"
  fi
  if has_env_or_file_value DASHSCOPE_API_KEY; then
    base_url="$(env_or_file_value DASHSCOPE_BASE_URL || printf 'https://dashscope.aliyuncs.com/compatible-mode/v1')"
    append_host_from_url hosts "$base_url"
  fi

  local joined=""
  local host
  for host in "${hosts[@]}"; do
    joined="${joined:+$joined,}$host"
  done
  printf '%s' "$joined"
}

base_run_args() {
  local -n _target_args="$1"
  _target_args=(
    run
    -d
    --name "$CONTAINER_NAME"
    --read-only
    --cap-drop ALL
    --security-opt no-new-privileges:true
    --pids-limit "${OPENCLAW_DOCKER_PIDS:-256}"
    --memory "${OPENCLAW_DOCKER_MEMORY:-4g}"
    --cpus "${OPENCLAW_DOCKER_CPUS:-2}"
    --user "${APP_UID}:${APP_GID}"
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size="${OPENCLAW_DOCKER_TMP_SIZE:-512m}",mode=1777
    --tmpfs /run:rw,nosuid,nodev,size=64m,uid="${APP_UID}",gid="${APP_GID}",mode=0750
    --tmpfs /openclaw-runs:rw,nosuid,nodev,size="${OPENCLAW_DOCKER_RUNS_SIZE:-512m}",uid="${APP_UID}",gid="${APP_GID}",mode=0750
    --tmpfs /workspace:rw,nosuid,nodev,size="${OPENCLAW_DOCKER_WORKSPACE_SIZE:-1g}",uid="${APP_UID}",gid="${APP_GID}",mode=0750
    --mount "type=bind,src=$ROOT_DIR,dst=/repo,readonly"
    -e OPENCLAW_HOST=0.0.0.0
    -e OPENCLAW_PORT=8787
    -e OPENCLAW_DATA_DIR=/openclaw-runs
    -e OPENCLAW_WORKSPACE=/repo
    -e OPENCLAW_ENFORCE_WORKSPACE_BOUNDARY=1
    -e PYTHONDONTWRITEBYTECODE=1
    -e HOME=/tmp/openclaw
  )
  local key
  for key in "${ALLOWED_NON_SECRET_ENV_KEYS[@]}"; do
    if [[ -n "${!key:-}" ]]; then
      _target_args+=("-e" "$key=${!key}")
    fi
  done
}

gateway_run_args() {
  local -n _target_args="$1"
  _target_args=(
    run
    -d
    --name "$GATEWAY_NAME"
    --read-only
    --cap-drop ALL
    --security-opt no-new-privileges:true
    --pids-limit 128
    --memory 256m
    --cpus 0.5
    --user 10001:10001
    --no-healthcheck
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777
    --network bridge
    -p "127.0.0.1:${HOST_PORT}:8788"
  )
}

api_proxy_run_args() {
  local -n _target_args="$1"
  _target_args=(
    run
    -d
    --name "$API_PROXY_NAME"
    --read-only
    --cap-drop ALL
    --security-opt no-new-privileges:true
    --pids-limit 128
    --memory 256m
    --cpus 0.5
    --user 10001:10001
    --no-healthcheck
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777
    --network bridge
  )
}

run_isolated() {
  require_docker
  ensure_internal_network
  stop_container
  local args=()
  base_run_args args
  args+=(--network "$INTERNAL_NETWORK")
  docker "${args[@]}" "$IMAGE_NAME"
  local gateway_args=()
  gateway_run_args gateway_args
  docker "${gateway_args[@]}" "$IMAGE_NAME" \
    python /opt/openclaw/tcp_forward.py \
    --listen-host 0.0.0.0 \
    --listen-port 8788 \
    --target-host "$CONTAINER_NAME" \
    --target-port 8787
  docker network connect "$INTERNAL_NETWORK" "$GATEWAY_NAME"
  echo "OpenClaw is running at http://127.0.0.1:${HOST_PORT} with no external egress."
}

run_api() {
  require_docker
  ensure_internal_network
  stop_container
  local allow_hosts
  allow_hosts="$(collect_api_proxy_allow_hosts)"
  if [[ -z "$allow_hosts" ]]; then
    echo "No model API key/base URL found. Fill deploy/openclaw-api.env or set OPENCLAW_API_PROXY_ALLOW_HOSTS." >&2
    exit 1
  fi

  local args=()
  base_run_args args
  args+=(
    --network "$INTERNAL_NETWORK"
    -e "HTTPS_PROXY=http://${API_PROXY_NAME}:8790"
    -e "HTTP_PROXY=http://${API_PROXY_NAME}:8790"
    -e "NO_PROXY=127.0.0.1,localhost,${CONTAINER_NAME},${GATEWAY_NAME},${API_PROXY_NAME}"
  )
  append_env_from_file args "$API_ENV_FILE"
  append_env_from_current args "${ALLOWED_API_ENV_KEYS[@]}"
  docker "${args[@]}" "$IMAGE_NAME"

  local gateway_args=()
  gateway_run_args gateway_args
  docker "${gateway_args[@]}" "$IMAGE_NAME" \
    python /opt/openclaw/tcp_forward.py \
    --listen-host 0.0.0.0 \
    --listen-port 8788 \
    --target-host "$CONTAINER_NAME" \
    --target-port 8787
  docker network connect "$INTERNAL_NETWORK" "$GATEWAY_NAME"

  local proxy_args=()
  api_proxy_run_args proxy_args
  docker "${proxy_args[@]}" \
    -e "OPENCLAW_PROXY_ALLOW_HOSTS=$allow_hosts" \
    "$IMAGE_NAME" \
    python /opt/openclaw/https_connect_proxy.py \
    --listen-host 0.0.0.0 \
    --listen-port 8790 \
    --allow-hosts "$allow_hosts"
  docker network connect "$INTERNAL_NETWORK" "$API_PROXY_NAME"

  echo "OpenClaw is running at http://127.0.0.1:${HOST_PORT} with model API egress limited to: $allow_hosts"
  echo "Only allowlisted API/provider environment variables were injected into the app container."
}

show_status() {
  require_docker
  docker ps --format '{{.Names}}\t{{.ID}}\t{{.Status}}\t{{.Ports}}' \
    | grep -E "^(${CONTAINER_NAME}|${GATEWAY_NAME}|${API_PROXY_NAME})[[:space:]]" || true
}

case "${1:-}" in
  build)
    build_image
    ;;
  run)
    run_isolated
    ;;
  run-api)
    run_api
    ;;
  stop)
    stop_container
    ;;
  logs)
    require_docker
    docker logs -f "$CONTAINER_NAME"
    ;;
  status)
    show_status
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
