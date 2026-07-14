# OpenClaw CLI Harness for EvalScope

This package registers an EvalScope external-agent runner named
`openclaw-cli-harness`. The runner evaluates OpenClaw as a CLI harness:

```text
EvalScope ExternalAgentConfig -> runner -> openclaw agent --json -> OpenClaw Gateway -> EvalScope bridge
```

The OpenClaw Gateway stays running in Docker Compose. The runner does not use
OpenClaw's `/v1/responses` endpoint as the scored path; that endpoint is useful
only for service smoke tests.

## Build Images

Build the baseline image from the source snapshot:

```bash
PROXY="socks5://$(ip route show default | awk '{print $3}'):7890"

docker build \
  --build-arg ALL_PROXY="$PROXY" \
  --build-arg HTTPS_PROXY="$PROXY" \
  --build-arg HTTP_PROXY="$PROXY" \
  -t openclaw-baseline:2026.6.11-srcsnap \
  -f openclaw-main/Dockerfile openclaw-main
```

Build a modified image from your experiment source with the same Dockerfile:

```bash
docker build \
  --build-arg ALL_PROXY="$PROXY" \
  --build-arg HTTPS_PROXY="$PROXY" \
  --build-arg HTTP_PROXY="$PROXY" \
  -t openclaw-modified:<experiment-id> \
  -f openclaw-exp/Dockerfile openclaw-exp
```

If Docker cannot pull base images through the proxy, configure the Docker
daemon or Docker client proxy as well; build args only affect build steps after
the base image is available.

## Router Overlay Images

The Router experiment does not rebuild OpenClaw. It creates two independent
images on top of the existing baseline:

- `openclaw-router-gateway`: the baseline image plus the Router provider plugin
  and OpenClaw's official Prometheus diagnostics extension.
- `openclaw-router-api`: the Python XGBoost routing sidecar and its model/PCA
  artifacts.

Build both images from the repository root:

```bash
export OPENCLAW_ROUTER_BASE_IMAGE=openclaw-baseline:2026.6.11-srcsnap
export OPENCLAW_ROUTER_GATEWAY_IMAGE=openclaw-router-gateway:2026.6.11-overlay
export OPENCLAW_ROUTER_API_IMAGE=openclaw-router-api:2026.6.11

bash openclaw_evalscope_cli/build_router_images.sh
```

The Gateway overlay Dockerfile only creates directories and copies files. It
does not run `pnpm install`, `npm install`, or rebuild OpenClaw. The Router API
uses the Aliyun PyPI mirror by default. If only its `apt`/`pip` build steps need
an HTTP proxy, set:

```bash
PROXY_HOST="$(ip route show default | awk '{print $3}')"
export OPENCLAW_ROUTER_BUILD_HTTP_PROXY="http://${PROXY_HOST}:7890"
bash openclaw_evalscope_cli/build_router_images.sh
```

That variable is passed only to the Router API build. It is deliberately not
passed to the OpenClaw overlay, so no pnpm command can inherit it. Base-image
pulls use the Docker daemon's own proxy configuration.

Confirm that the baseline itself was not replaced:

```bash
docker image inspect \
  openclaw-baseline:2026.6.11-srcsnap \
  openclaw-router-gateway:2026.6.11-overlay \
  --format '{{.RepoTags}} {{.Id}} {{.Size}}'
```

Use separate Compose projects, ports, state, and secret directories for a
baseline/Router comparison. Never point both experiments at the same OpenClaw
state directory.

## Router EvalScope Run

Router mode adds `docker-compose.router.yml` automatically and keeps strict
bridge routing enabled. The tier values must be keys in
`EVALSCOPE_ROUTER_MODEL_ROUTES`:

```bash
export OPENCLAW_ROUTER_ENABLED=true
export OPENCLAW_ROUTER_GATEWAY_IMAGE=openclaw-router-gateway:2026.6.11-overlay
export OPENCLAW_ROUTER_API_IMAGE=openclaw-router-api:2026.6.11
export OPENCLAW_COMPOSE_PROJECT=openclaw-eval-router-gsm8k
export OPENCLAW_GATEWAY_PORT=18889
export OPENCLAW_EVAL_STATE_DIR="$PWD/openclaw_evalscope_cli/.openclaw-eval/router/gsm8k/state"
export OPENCLAW_EVAL_SECRET_DIR="$PWD/openclaw_evalscope_cli/.openclaw-eval/router/gsm8k/secrets"

export OPENCLAW_ROUTER_TIERS='{
  "small": "qwen-flash",
  "mid": "qwen-plus",
  "large": "qwen-max"
}'

export EVALSCOPE_ROUTER_MODEL_ROUTES='{
  "qwen-flash": {
    "model_id": "qwen3.6-plus",
    "eval_type": "openai_api",
    "api_url": "https://example.com/compatible-mode/v1",
    "api_key_env": "EVALSCOPE_API_KEY",
    "openclaw_model": {
      "reasoning": false,
      "contextWindow": 131072,
      "maxTokens": 8192,
      "cost": {"input": 1, "output": 4, "cacheRead": 0.2, "cacheWrite": 1}
    }
  },
  "qwen-plus": {
    "model_id": "qwen3.7-plus",
    "eval_type": "openai_api",
    "api_url": "https://example.com/compatible-mode/v1",
    "api_key_env": "EVALSCOPE_API_KEY",
    "openclaw_model": {
      "reasoning": true,
      "contextWindow": 131072,
      "maxTokens": 8192,
      "cost": {"input": 3, "output": 12, "cacheRead": 0.6, "cacheWrite": 3}
    }
  },
  "qwen-max": {
    "model_id": "qwen3.7-max",
    "eval_type": "openai_api",
    "api_url": "https://example.com/compatible-mode/v1",
    "api_key_env": "EVALSCOPE_API_KEY",
    "openclaw_model": {
      "reasoning": true,
      "contextWindow": 131072,
      "maxTokens": 8192,
      "cost": {"input": 10, "output": 40, "cacheRead": 2, "cacheWrite": 10}
    }
  }
}'

export EVALSCOPE_MODEL=qwen3.7-max
export EVALSCOPE_MODEL_ID=openclaw_router_gsm8k
export EVALSCOPE_EVAL_TYPE=openai_api
export EVALSCOPE_API_URL=https://example.com/compatible-mode/v1
export EVALSCOPE_API_KEY='...'
export EVALSCOPE_DATASET=gsm8k
export EVALSCOPE_LIMIT=5
export EVALSCOPE_BATCH_SIZE=1
export EVALSCOPE_JUDGE_STRATEGY=rule

python -m openclaw_evalscope_cli.run_evalscope
```

The `cost` values are prices per million tokens, not benchmark weights. Replace
the example values with the provider's current prices. Router mode calculates
cost per bridge call using the model actually selected; it does not apply the
single-model `EVALSCOPE_INPUT_PRICE_PER_MILLION` setting.

The final `experiment_report.json` contains:

- `routing.calls_by_model` and `routing.calls_by_tier`.
- Per-task `model_calls` with requested/resolved model and usage.
- `cost_estimate.cost_by_model` plus task min/mean/max cost.
- `openclaw_runtime_metrics.prometheus_counter_delta` from OpenClaw's own
  diagnostics exporter.

OpenClaw's Prometheus labels describe the original `router-entry` harness
model. Use the EvalScope bridge trace as the source of truth for the selected
target model and per-model token cost. Judge, analysis-report, subscription,
tax, and external tool-service charges are excluded.

## Compose Expectations

The default example uses
`openclaw_evalscope_cli/docker-compose.evalscope.yml`, which defines:

- `openclaw-gateway`: long-running Gateway service.
- `openclaw-cli`: one-off CLI service sharing the Gateway state volumes.
- `host.docker.internal:host-gateway` reachable from the containers.

It stores state in `./.openclaw-eval/` by default. Use different project names,
ports, state directories, and images for baseline vs modified runs:

```bash
export OPENCLAW_IMAGE=openclaw-baseline:2026.6.11-srcsnap
export OPENCLAW_COMPOSE_PROJECT=openclaw-eval-baseline
export OPENCLAW_GATEWAY_PORT=18789
export OPENCLAW_EVAL_STATE_DIR="$PWD/.openclaw-eval/baseline/state"
export OPENCLAW_EVAL_SECRET_DIR="$PWD/.openclaw-eval/baseline/secrets"
```

For a modified image, switch those values:

```bash
export OPENCLAW_IMAGE=openclaw-modified:<experiment-id>
export OPENCLAW_COMPOSE_PROJECT=openclaw-eval-modified
export OPENCLAW_GATEWAY_PORT=18799
export OPENCLAW_EVAL_STATE_DIR="$PWD/.openclaw-eval/modified/state"
export OPENCLAW_EVAL_SECRET_DIR="$PWD/.openclaw-eval/modified/secrets"
```

The repository's OpenClaw `docker-compose.yml` also follows the gateway/cli
shape, so you can override `OPENCLAW_COMPOSE_FILES` if you prefer to use it.

## Run EvalScope

First-run smoke defaults to EvalScope `MockLLM` and `limit=1`:

```bash
bash openclaw_evalscope_cli/run_evalscope.sh
```

Useful environment variables:

```bash
export OPENCLAW_COMPOSE_PROJECT=openclaw-eval-baseline
export OPENCLAW_GATEWAY_SERVICE=openclaw-gateway
export OPENCLAW_CLI_SERVICE=openclaw-cli
export OPENCLAW_AGENT_ID=main

export EVALSCOPE_DATASET=gsm8k
export EVALSCOPE_LIMIT=5
export EVALSCOPE_MODEL=mock
export EVALSCOPE_EVAL_TYPE=mock_llm
```

For a real upstream model, set the normal EvalScope model fields:

```bash
export EVALSCOPE_MODEL=qwen-plus
export EVALSCOPE_EVAL_TYPE=openai_api
export EVALSCOPE_API_URL=https://example.com/v1/chat/completions
export EVALSCOPE_API_KEY=...
```

Judge scoring defaults to EvalScope's `auto` strategy. Benchmarks such as
BrowseComp will therefore use an LLM judge. By default the judge reuses the
evaluated model connection; override it with separate settings when needed:

```bash
export EVALSCOPE_JUDGE_STRATEGY=auto
export EVALSCOPE_JUDGE_MODEL=qwen-plus
export EVALSCOPE_JUDGE_EVAL_TYPE=openai_api
export EVALSCOPE_JUDGE_API_URL="$EVALSCOPE_API_URL"
export EVALSCOPE_JUDGE_API_KEY="$EVALSCOPE_API_KEY"
export EVALSCOPE_JUDGE_TEMPERATURE=0.0
export EVALSCOPE_JUDGE_MAX_TOKENS=4096
```

`EVALSCOPE_JUDGE_MODEL_ARGS` may be used for a complete JSON configuration;
the judge model field is named `model_id`. Judge calls are not included in
the evaluated harness token totals.

With `EVALSCOPE_COLLECT_PERF=true` (the default), prediction JSONL files carry
per-task usage in `model_output.metadata.task_usage`. Dataset report JSON,
console tables, and HTML reports include total and avg/min/max tokens per task.

The runner rewrites the per-sample OpenClaw provider to the EvalScope bridge:

- `models.providers.evalscope.baseUrl = <bridge>/openai/v1`
- `models.providers.evalscope.apiKey = <trial token>`
- `models.providers.evalscope.api = openai-responses`
- `openclaw agent --model evalscope/<EVALSCOPE_MODEL>`

Keep `eval_batch_size=1` for this v1 harness because the bridge token is stored
in the evaluation-only OpenClaw config before each sample.

Because the OpenClaw container dials the EvalScope bridge from Docker, the
example sets `agent_config.bridge.proxy_host` to `0.0.0.0` and rewrites
loopback bridge URLs to `host.docker.internal` inside the runner.

## Local CLI Debug

You can debug plain OpenClaw CLI JSON extraction without EvalScope:

```bash
python3 -m openclaw_evalscope_cli \
  --openclaw-bin openclaw \
  --agent main \
  --model evalscope/mock \
  --prompt "Reply exactly: OPENCLAW_OK"
```
