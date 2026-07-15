ARG BASE_IMAGE=openclaw-baseline:2026.6.11-srcsnap
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.title="OpenClaw Context Index Overlay" \
      org.opencontainers.image.description="OpenClaw baseline plus the Context Index context-engine plugin"

USER root

RUN rm -rf /opt/openclaw-plugins/context-index && \
    install -d -o node -g node \
      /opt/openclaw-plugins/context-index/src \
      /opt/openclaw-plugins/context-index/node_modules

COPY --chown=node:node \
  package.json \
  openclaw.plugin.json \
  index.ts \
  README.md \
  /opt/openclaw-plugins/context-index/

COPY --chown=node:node src/ /opt/openclaw-plugins/context-index/src/

# The baseline already contains these production dependencies. Keeping the
# overlay dependency-free avoids repeating OpenClaw's full pnpm/build pipeline.
RUN ln -s /app/node_modules/commander /opt/openclaw-plugins/context-index/node_modules/commander && \
    node -e "Promise.all([import('commander'), import('openclaw/plugin-sdk/plugin-entry'), import('openclaw/plugin-sdk/core')]).catch((error) => { console.error(error); process.exit(1); })"

USER node
