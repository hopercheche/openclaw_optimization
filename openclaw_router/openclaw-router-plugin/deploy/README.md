# OpenClaw Router API

Standalone HTTP sidecar for the OpenClaw Router plugin. It loads the packaged
XGBoost classifier and PCA transformer, extracts prompt features, and returns a
`small`, `mid`, or `large` decision.

## Container Build

Normally use the parent project's two-image build script. To build only this
sidecar:

```bash
docker build \
  --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple \
  -t openclaw-router-api:2026.6.11 \
  openclaw_router/openclaw-router-plugin/deploy
```

The default image uses the lightweight hash embedding backend. To include BGE
dependencies:

```bash
docker build \
  --build-arg INSTALL_BGE=1 \
  --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple \
  -t openclaw-router-api:2026.6.11-bge \
  openclaw_router/openclaw-router-plugin/deploy
```

## Run

```bash
docker run --rm -p 3000:3000 \
  -e EMBEDDING_MODE=hash \
  openclaw-router-api:2026.6.11
```

Supported environment variables:

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | Listen address |
| `PORT` | `3000` | Listen port |
| `EMBEDDING_MODE` | `hash` | Feature embedding backend |
| `ROUTER_API_KEY` | empty | Optional bearer token for prediction routes |
| `ROUTER_MODEL_PATH` | packaged pickle | Override XGBoost artifact |
| `ROUTER_PCA_PATH` | packaged pickle | Override PCA artifact |

## Endpoints

### `GET /health`

Returns readiness plus the embedding backend and model/PCA SHA-256 digests.

### `POST /predict`

Returns the classifier's raw tier, confidence, probabilities, and compact
features.

```json
{"query": "Explain quantum computing"}
```

### `POST /route`

Applies the confidence threshold and cascade policy. EvalScope correlation
fields are optional.

```json
{
  "query": "Explain quantum computing",
  "confidence_threshold": 0.5,
  "request_id": "request-123",
  "eval_sample_id": "42"
}
```

Example:

```bash
curl -fsS http://127.0.0.1:3000/health
curl -fsS http://127.0.0.1:3000/route \
  -H 'Content-Type: application/json' \
  -d '{"query":"What is 2+2?","confidence_threshold":0.5}'
```

If `ROUTER_API_KEY` is configured, add:

```bash
-H "Authorization: Bearer $ROUTER_API_KEY"
```

The service logs structured JSON for startup, route decisions, and failures.

## Artifact Compatibility

The current XGBoost pickle was produced by an older XGBoost release. XGBoost
3.3 loads it with a warning, but a stable release artifact should be exported
from the training version with `Booster.save_model()` and repackaged. Also
confirm that `EMBEDDING_MODE` matches the embedding pipeline used during
training; a backend mismatch changes the classifier input distribution.
