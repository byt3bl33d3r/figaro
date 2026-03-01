# Figaro Supervisor
# Stage 1: Build Python wheel and download dependencies
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS python-builder

WORKDIR /app

# Copy shared library first (needed as build dependency)
COPY figaro-nats/ /app/figaro-nats/

# Copy supervisor source
COPY figaro-supervisor/ /app/figaro-supervisor/

WORKDIR /app/figaro-supervisor
RUN uv build /app/figaro-nats --out-dir /wheels \
    && uv build . --out-dir /wheels

# Export all dependencies (including transitive) and download as wheels
RUN uv export --frozen --no-emit-project --no-hashes > /tmp/requirements.txt && \
    pip download -r /tmp/requirements.txt -d /wheels

# Stage 2: Final image
FROM python:3.14-slim

RUN apt-get update && apt-get install --no-install-recommends -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for Claude Code
RUN useradd -m -s /bin/bash supervisor
USER supervisor
RUN curl -fsSL https://claude.ai/install.sh | bash

# Switch back to root for wheel install (bind mount is root-owned)
USER root
RUN --mount=type=bind,from=python-builder,source=/wheels,target=/wheels \
    pip3 install --no-index --find-links=/wheels /wheels/figaro_supervisor-*.whl

USER supervisor
CMD ["figaro-supervisor"]