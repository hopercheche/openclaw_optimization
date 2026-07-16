# OpenClaw Three-Plugin Public Demo

This directory runs one persistent OpenClaw Gateway with the following project
plugins enabled together:

- `openclaw-router`: selects a small, mid, or large model through the Router API.
- `context-index`: provides the active progressive context-engine slot.
- `task-compass`: injects a deterministic planning route before prompt assembly.

The browser uses OpenClaw's original Control UI. The Router API remains a
separate sidecar because the Router plugin calls its HTTP classification API.
The `openclaw-cli` Compose service is only an on-demand management client.

## 1. Build The Demo Overlay

The following images must already exist:

```bash
docker image inspect openclaw-router-gateway:2026.6.11-overlay
docker image inspect openclaw-router-api:2026.6.11
```

Build the thin three-plugin layer:

```bash
cd /home/featurize/work/ProjectAgentScope/openclaw_optimization
bash demo/build.sh
```

The build reuses the Router Gateway image, generates the existing Task Compass
release bundle, and copies Context Index. It does not rebuild OpenClaw and does
not run `pnpm install`.

## 2. Configure The Public Demo

Edit the configuration block at the top of `demo/start.sh`. At minimum replace:

```bash
OPENCLAW_DEMO_PUBLIC_ORIGIN="https://your-platform-public-url"
OPENCLAW_DEMO_GATEWAY_TOKEN="a-long-random-demo-token"
OPENCLAW_DEMO_MODEL_API_URL="https://your-provider.example/v1"
OPENCLAW_DEMO_MODEL_API_KEY="your-dedicated-demo-key"
```

The public origin must contain only the HTTPS scheme and host. Do not include a
path, query, fragment, or `#token` value. The platform proxy must support
WebSocket Upgrade and forward traffic to `OPENCLAW_DEMO_PORT`.

If the platform only provides plain HTTP, explicitly opt into the insecure Demo
mode at the top of `start.sh`:

```bash
OPENCLAW_DEMO_PUBLIC_ORIGIN="http://your-public-host:port"
OPENCLAW_DEMO_ALLOW_HTTP="true"
```

HTTP is disabled by default. This override is appropriate only for a disposable
public Demo because the shared Gateway token and browser traffic are not
protected by TLS.

The real model API key is resolved from the Gateway environment through an
OpenClaw SecretRef. It is not written to the image or `openclaw.json`.

## 3. One-Click Start

```bash
bash demo/start.sh
```

The script validates configuration and images, starts the Router API and
Gateway, waits for health checks, verifies all three plugins, and prints a URL
similar to:

```text
https://your-platform-public-url/#token=<encoded-demo-token>
```

The token is stored in the URL fragment, so browsers deliver it to the Control
UI without sending it in the HTTP request path. Device pairing is disabled for
this dedicated Demo Gateway.

### One-Click ngrok Start

Set the ngrok authtoken at the top of `start.sh`:

```bash
OPENCLAW_DEMO_NGROK_AUTHTOKEN="your-ngrok-authtoken"
```

Then run:

```bash
bash demo/start-ngrok.sh
```

The script runs the official `ngrok/ngrok` container, reads its HTTPS endpoint
from the local ngrok API, configures that exact endpoint as OpenClaw's allowed
Control UI origin, verifies that device authentication is disabled, and prints
the complete `#token=` URL. No HTTP override is needed for ngrok.

Stop both OpenClaw and ngrok while preserving OpenClaw volumes:

```bash
bash demo/stop-ngrok.sh
```

## 4. Smoke And Operations

Run a real model request and verify Router activity:

```bash
bash demo/smoke.sh
```

Inspect or stop the deployment without deleting data:

```bash
bash demo/status.sh
bash demo/stop.sh
```

Start it again with `bash demo/start.sh`; named volumes preserve sessions,
workspace files, configuration, and Context Index data.

Permanently remove all Demo state:

```bash
bash demo/reset.sh
# Non-interactive destructive form:
bash demo/reset.sh --yes
```

## Port Already In Use

If startup reports that the host port is already in use, inspect the owner:

```bash
docker ps --filter publish=18789 --format 'table {{.Names}}\t{{.Ports}}'
sudo ss -ltnp 'sport = :18789'
```

Stop an obsolete container only after identifying it. If the existing service
must remain running, change both `OPENCLAW_DEMO_PORT` and the port in the public
forwarding URL, for example from `18789` to `18889`. After a failed partial
startup, `bash demo/stop.sh` removes the Demo containers while preserving its
named volumes.

## Security Boundary

The generated link grants shared, full Control UI operator access. Visitors can
see the same sessions and long-lived state. Use a dedicated API key with a hard
spending limit, never place private files in the Demo workspace, and do not
mount the Docker socket or host project directories into the Gateway.

The default `OPENCLAW_DEMO_TOOL_PROFILE=minimal` and disabled operator terminal
reduce the initial tool surface. Full Control UI administrators can still alter
runtime configuration, so this deployment is a public experiment environment,
not a boundary for production secrets.

Because this project intentionally keeps environment values at the top of
`start.sh`, check `git diff -- demo/start.sh` before committing after entering a
real API key.
