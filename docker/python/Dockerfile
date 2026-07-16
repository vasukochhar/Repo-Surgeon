FROM ghcr.io/google/osv-scanner:v2.4.0 AS osv
FROM python:3.12-slim
COPY --from=osv /osv-scanner /usr/local/bin/osv-scanner
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential ca-certificates \
 && pip install --no-cache-dir pytest pytest-cov coverage pip-audit mutmut build \
 && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 surgeon
USER surgeon
WORKDIR /workspace
