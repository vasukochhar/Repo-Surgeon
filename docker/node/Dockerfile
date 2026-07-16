FROM ghcr.io/google/osv-scanner:v2.4.0 AS osv
FROM node:22-bookworm-slim
COPY --from=osv /osv-scanner /usr/local/bin/osv-scanner
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential ca-certificates procps \
 && corepack enable \
 && corepack prepare pnpm@10.14.0 --activate \
 && corepack prepare yarn@1.22.22 --activate \
 && npm install --global @stryker-mutator/core @stryker-mutator/jest-runner @stryker-mutator/vitest-runner \
 && npm cache clean --force \
 && rm -rf /var/lib/apt/lists/*
USER node
WORKDIR /workspace
