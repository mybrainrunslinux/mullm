FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY router ./router
RUN python -m pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim
LABEL org.opencontainers.image.title="muLLM"
LABEL org.opencontainers.image.licenses="Apache-2.0"
RUN groupadd --gid 1001 mullm && useradd --uid 1001 --gid mullm --create-home mullm
COPY --from=builder /install /usr/local
RUN mkdir -p /data && chown mullm:mullm /data
USER mullm
WORKDIR /data
ENV MULLM_PORT=6856 MULLM_STATE_DIR=/data MULLM_DEV_MODE=false \
    MULLM_OPEN_BROWSER=0 MULLM_REMOTE_ACCESS=true PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 MULLM_OLLAMA_BASE_URL=http://host.containers.internal:11434
EXPOSE 6856
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import pathlib,ssl,urllib.request; c=pathlib.Path('/data/cache/data/certs/mullm.crt'); ctx=ssl.create_default_context(cafile=str(c)) if c.exists() else None; urllib.request.urlopen(('https' if ctx else 'http')+'://127.0.0.1:6856/health', context=ctx, timeout=4).read()"
CMD ["mullm-server"]
