# muLLM production Dockerfile
# Multi-stage: builder installs deps, runtime is minimal.
# podman-compatible (no Docker-specific features).
#
# Build:   podman build -t mullm:1.0.0 .
# Run:     podman run -p 6856:6856 --env-file .env mullm:1.0.0

# ── Stage 1: builder ─────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# System build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps into a prefix we can copy
COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install \
        "fastapi>=0.115,<1.0" \
        "uvicorn[standard]>=0.32,<1.0" \
        "pydantic>=2.10,<3.0" \
        "pydantic-settings>=2.6,<3.0" \
        "httpx>=0.27,<1.0" \
        "anthropic>=0.50,<1.0" \
        "openai>=1.60,<3.0" \
        "psutil>=6.0,<7.0" \
        "chromadb>=1.0,<2.0" \
        "rich>=13.0,<15.0" \
        "python-dotenv>=1.0,<2.0" \
        "structlog>=24.0,<26.0"


# ── Stage 2: runtime ─────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="muLLM"
LABEL org.opencontainers.image.description="Local-first LLM router — 96.4% cost reduction"
LABEL org.opencontainers.image.version="1.0.0"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL org.opencontainers.image.url="https://github.com/mybrainrunslinux/mullm"

# Non-root user
RUN groupadd --gid 1001 mullm && \
    useradd  --uid 1001 --gid mullm --shell /bin/bash --create-home mullm

# Copy installed packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy application source
COPY router/ ./router/

# Data directories (scoring log, chromadb cache)
RUN mkdir -p /data/cache/data && \
    chown -R mullm:mullm /data /app

USER mullm

# Environment defaults (override via --env-file)
ENV MULLM_PORT=6856 \
    MULLM_DEV_MODE=false \
    MULLM_OPEN_BROWSER=0 \
    MULLM_LOG_LEVEL=INFO \
    MULLM_OLLAMA_BASE_URL=http://host.containers.internal:11434 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Override cache dir to /data
ENV MULLM_CACHE_DIR=/data/cache/data

EXPOSE 6856

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:6856/health').read()" || exit 1

CMD ["python", "-m", "router.main"]
