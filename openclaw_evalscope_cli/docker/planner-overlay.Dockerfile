ARG BASE_IMAGE=openclaw-baseline:2026.6.11-srcsnap
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.title="OpenClaw Task Compass Planner Overlay" \
      org.opencontainers.image.description="OpenClaw baseline plus the Task Compass native planner plugin"

USER root

RUN rm -rf /opt/openclaw-plugins/task-compass && \
    install -d -o node -g node /opt/openclaw-plugins/task-compass

COPY --chown=node:node . /opt/openclaw-plugins/task-compass/

# Fail the overlay build if either the OpenClaw runtime surface or the bundled
# offline Python router is missing. No package installation is required.
RUN node -e "import('openclaw/plugin-sdk/plugin-entry').catch((error) => { console.error(error); process.exit(1); })" && \
    python3 /opt/openclaw-plugins/task-compass/skills/task-compass/scripts/route_task.py \
      --goal "Read the project status without modifying files." >/tmp/task-compass-route.json && \
    node -e "const fs=require('fs'); const value=JSON.parse(fs.readFileSync('/tmp/task-compass-route.json','utf8')); if(value.schema_version!=='1.0') process.exit(1)" && \
    rm -f /tmp/task-compass-route.json

USER node
