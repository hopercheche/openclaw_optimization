ARG BASE_IMAGE=openclaw-router-gateway:2026.6.11-overlay
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.title="OpenClaw Three-Plugin Public Demo" \
      org.opencontainers.image.description="OpenClaw Router plus Context Index and Task Compass"

USER root

RUN rm -rf \
      /opt/openclaw-plugins/context-index \
      /opt/openclaw-plugins/task-compass && \
    install -d -o node -g node \
      /opt/openclaw-demo \
      /opt/openclaw-plugins/context-index/node_modules \
      /opt/openclaw-plugins/task-compass

COPY --chown=node:node context-index/ /opt/openclaw-plugins/context-index/
COPY --chown=node:node task-compass/ /opt/openclaw-plugins/task-compass/
COPY --chown=node:node init.mjs /opt/openclaw-demo/init.mjs

# Context Index reuses Commander from the baseline image. Task Compass is an
# already validated release bundle, so the demo layer needs no package install.
RUN ln -s /app/node_modules/commander \
      /opt/openclaw-plugins/context-index/node_modules/commander && \
    test -f /opt/openclaw-plugins/openclaw-router/openclaw.plugin.json && \
    test -f /opt/openclaw-plugins/context-index/openclaw.plugin.json && \
    test -f /opt/openclaw-plugins/task-compass/openclaw.plugin.json && \
    node -e "Promise.all([import('commander'), import('openclaw/plugin-sdk/plugin-entry'), import('openclaw/plugin-sdk/core')]).catch((error) => { console.error(error); process.exit(1); })" && \
    python3 /opt/openclaw-plugins/task-compass/skills/task-compass/scripts/route_task.py \
      --goal "Inspect the public demo without modifying files." >/tmp/task-compass-demo-route.json && \
    node -e "const fs=require('fs'); const value=JSON.parse(fs.readFileSync('/tmp/task-compass-demo-route.json','utf8')); if(value.schema_version!=='1.0') process.exit(1)" && \
    rm -f /tmp/task-compass-demo-route.json

USER node
