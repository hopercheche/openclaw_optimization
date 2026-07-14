# OpenClaw Router Plugin

This plugin registers the `openclaw-router` provider. Each OpenClaw model call
is classified by the Router API as `small`, `mid`, or `large`, then forwarded
through the original OpenClaw stream transport with the selected target model.

## Components

```text
openclaw-router-plugin/
├── openclaw.plugin.json
├── package.json
├── src/
│   ├── index.ts
│   └── router-client.ts
└── deploy/
    ├── Dockerfile
    ├── server.py
    ├── requirements.txt
    ├── requirements-bge.txt
    ├── models/router_xgboost_epsilon_0.2.pkl
    └── data/pca_transformer.pkl
```

The EvalScope integration builds the plugin as a source overlay on the existing
OpenClaw baseline. OpenClaw's runtime loader handles the TypeScript entrypoint,
so this path does not run `npm install`, `pnpm install`, or `npm run build`.

## Build With The EvalScope Project

From the parent project root:

```bash
export OPENCLAW_ROUTER_BASE_IMAGE=openclaw-baseline:2026.6.11-srcsnap
export OPENCLAW_ROUTER_GATEWAY_IMAGE=openclaw-router-gateway:2026.6.11-overlay
export OPENCLAW_ROUTER_API_IMAGE=openclaw-router-api:2026.6.11

bash openclaw_evalscope_cli/build_router_images.sh
```

The resulting deployment uses an independent Router API sidecar. Do not copy
Python dependencies or model artifacts into the OpenClaw Gateway image.

## OpenClaw Configuration

The EvalScope runner writes this configuration automatically. A manual
equivalent is:

```json
{
  "models": {
    "providers": {
      "openclaw-router": {
        "api": "openai-responses",
        "baseUrl": "http://host.docker.internal:40907/openai/v1",
        "apiKey": "evalscope-trial-token",
        "models": [
          {"id": "router-entry", "name": "router-entry"},
          {"id": "small-model", "name": "small-model"},
          {"id": "mid-model", "name": "mid-model"},
          {"id": "large-model", "name": "large-model"}
        ]
      }
    }
  },
  "plugins": {
    "load": {
      "paths": ["/opt/openclaw-plugins/openclaw-router"]
    },
    "allow": ["openclaw-router", "diagnostics-prometheus"],
    "entries": {
      "openclaw-router": {
        "enabled": true,
        "config": {
          "endpoint": "http://openclaw-router-api:3000",
          "confidenceThreshold": 0.5,
          "requestTimeoutMs": 5000,
          "strict": true,
          "tiers": {
            "small": "small-model",
            "mid": "mid-model",
            "large": "large-model"
          }
        }
      },
      "diagnostics-prometheus": {"enabled": true}
    }
  },
  "diagnostics": {"enabled": true}
}
```

`tiers` values are model IDs in the same `openclaw-router` provider. The plugin
changes the runtime model while retaining the provider's base URL, API key, API
protocol, and stream function. This is what lets EvalScope's strict bridge
dispatch each tier to a different model connection.

## Plugin Options

| Field | Type | Required | Description |
|---|---|---:|---|
| `endpoint` | string | yes | Router API base URL, without `/route` |
| `apiKey` | string | no | Router API bearer token; prefer `OPENCLAW_ROUTER_API_KEY` |
| `confidenceThreshold` | number | no | Direct/cascade threshold, default `0.5` |
| `requestTimeoutMs` | integer | no | Router request timeout, default `5000` |
| `strict` | boolean | no | Throw on Router failure instead of using the entry model |
| `evalSampleId` | string | no | EvalScope sample identifier for correlated logs |
| `tiers.small` | string | yes | Target model ID for the small tier |
| `tiers.mid` | string | yes | Target model ID for the mid tier |
| `tiers.large` | string | yes | Target model ID for the large tier |

Use `strict=true` for scored experiments. A silent fallback can hide Router
failures and make a comparison invalid.

## Router API

The sidecar listens on port `3000` by default:

```bash
docker run --rm -p 3000:3000 openclaw-router-api:2026.6.11

curl -fsS http://127.0.0.1:3000/health
curl -fsS http://127.0.0.1:3000/route \
  -H 'Content-Type: application/json' \
  -d '{"query":"Explain why the sky is blue","confidence_threshold":0.5}'
```

When `ROUTER_API_KEY` is set, `/predict` and `/route` require
`Authorization: Bearer <key>`. `/health` remains available to the container
health check.

The API emits structured `startup`, `route_decision`, and error logs. Health
output includes the embedding backend and SHA-256 digests of the XGBoost and
PCA artifacts.

## Metrics And Cost

The OpenClaw overlay also bundles the official `diagnostics-prometheus` plugin.
Its authenticated endpoint is:

```text
GET /api/diagnostics/prometheus
```

OpenClaw metrics cover harness runs, model-call timing, queueing, tools, and
runtime activity. The provider label remains `openclaw-router` and the model
label may remain `router-entry`; use EvalScope's bridge trace for selected-tier
model IDs, token usage, and per-model cost.

## Compatibility Notes

- Plugin API compatibility is declared as OpenClaw `>=2026.6.11`.
- The packaged XGBoost pickle currently loads with an old-serialization warning
  under XGBoost 3.3. Convert it to XGBoost's stable model format for long-term
  portability.
- `EMBEDDING_MODE=hash` is the lightweight default. Confirm it matches the
  training pipeline. Build with `OPENCLAW_ROUTER_INSTALL_BGE=1` and run with
  `OPENCLAW_ROUTER_EMBEDDING_MODE=bge` if the model was trained with BGE.
