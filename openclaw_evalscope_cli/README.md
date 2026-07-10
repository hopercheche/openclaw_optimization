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
