# Figaro Orchestrator + UI

# Stage 1: Build UI
FROM node:22-slim AS ui-builder

WORKDIR /app/figaro-ui
COPY figaro-ui/package*.json ./
RUN npm ci
COPY figaro-ui/ ./
RUN npm run build

# Stage 2: Build Python wheel and download dependencies
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS python-builder
WORKDIR /app

# Copy shared library first (needed as build dependency)
COPY figaro-nats/ /app/figaro-nats/

# Copy orchestrator source
COPY figaro/ /app/figaro/

WORKDIR /app/figaro
RUN uv build /app/figaro-nats --out-dir /wheels \
    && uv build . --out-dir /wheels
# Export all dependencies (including transitive) and download as wheels
RUN uv export --frozen --no-emit-project --no-hashes > /tmp/requirements.txt \
    && pip download -r /tmp/requirements.txt -d /wheels

# Stage 3: Final image
FROM python:3.14-slim
WORKDIR /app

# Install from wheels (mount temporarily so deps don't stay in image)
RUN --mount=type=bind,from=python-builder,source=/wheels,target=/wheels \
    pip3 install --no-index --find-links=/wheels /wheels/figaro-*.whl

# Copy built UI
COPY --from=ui-builder /app/figaro-ui/dist /app/static

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash figaro
USER figaro

ENV FIGARO_STATIC_DIR=/app/static
ENV FIGARO_HOST=0.0.0.0
ENV FIGARO_PORT=8000

EXPOSE 8000
# Single worker required: Registry stores WebSocket connections in-memory,
# so all connections must be handled by the same process.
# For horizontal scaling, use Redis-backed registry instead.
# Increase WebSocket ping timeout to prevent disconnections under load
# Default is 20s ping interval / 20s timeout, we increase to 60s/60s
CMD ["sh", "-c", "figaro-migrate && uvicorn figaro:app --host 0.0.0.0 --port 8000 --ws-ping-interval 60 --ws-ping-timeout 60"]
