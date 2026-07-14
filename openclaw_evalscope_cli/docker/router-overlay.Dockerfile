ARG BASE_IMAGE=openclaw-baseline:2026.6.11-srcsnap
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.title="OpenClaw EvalScope Router Overlay" \
      org.opencontainers.image.description="OpenClaw baseline plus the EvalScope router and Prometheus diagnostics plugins"

USER root

RUN install -d -o node -g node \
      /opt/openclaw-plugins/openclaw-router/src \
      /app/dist/extensions/diagnostics-prometheus/src

COPY --chown=node:node \
  openclaw_router/openclaw-router-plugin/package.json \
  openclaw_router/openclaw-router-plugin/openclaw.plugin.json \
  /opt/openclaw-plugins/openclaw-router/

COPY --chown=node:node \
  openclaw_router/openclaw-router-plugin/src/ \
  /opt/openclaw-plugins/openclaw-router/src/

COPY --chown=node:node \
  openclaw-main/extensions/diagnostics-prometheus/package.json \
  openclaw-main/extensions/diagnostics-prometheus/openclaw.plugin.json \
  openclaw-main/extensions/diagnostics-prometheus/api.ts \
  openclaw-main/extensions/diagnostics-prometheus/index.ts \
  /app/dist/extensions/diagnostics-prometheus/

COPY --chown=node:node \
  openclaw-main/extensions/diagnostics-prometheus/src/ \
  /app/dist/extensions/diagnostics-prometheus/src/

USER node
