# Build figaro-gateway wheel and download dependencies
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS python-builder

WORKDIR /app

# Copy shared library first (needed as build dependency)
COPY figaro-nats/ /app/figaro-nats/

# Copy gateway source
COPY figaro-gateway/ /app/figaro-gateway/

WORKDIR /app/figaro-gateway
RUN uv build /app/figaro-nats --out-dir /wheels \
    && uv build . --out-dir /wheels

# Export all dependencies (including transitive) and build/download as wheels
RUN uv export --frozen --no-emit-project --no-hashes > /tmp/requirements.txt && \
    pip wheel -r /tmp/requirements.txt -w /wheels

# Runtime stage
FROM python:3.14-slim-bookworm

RUN apt-get update && apt-get install --no-install-recommends -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install from wheels (mount temporarily so deps don't stay in image)
RUN --mount=type=bind,from=python-builder,source=/wheels,target=/wheels \
    pip3 install --no-index --find-links=/wheels /wheels/figaro_gateway-*.whl

RUN useradd -m -s /bin/bash gateway
USER gateway
CMD ["figaro-gateway"]
