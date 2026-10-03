# syntax=docker/dockerfile:1
# Runs the whole pipeline (fixture mode by default) in a reproducible image.
#   docker build -t jobpipe .
#   docker run --rm -v "$PWD/data:/data" jobpipe run
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    DBT_SEND_ANONYMOUS_USAGE_STATS=false

RUN pip install "uv==0.8.17"

WORKDIR /app

# Dependencies first so code edits do not invalidate this (slow) layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY transform ./transform
COPY config ./config
COPY fixtures ./fixtures
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 app && mkdir /data && chown app /data
USER app

ENV PATH="/app/.venv/bin:${PATH}" \
    JOBPIPE_DATA_DIR=/data \
    JOBPIPE_DBT_PROJECT_DIR=/app/transform \
    JOBPIPE_FIXTURES_DIR=/app/fixtures/responses \
    JOBPIPE_CONFIG_DIR=/app/config

VOLUME ["/data"]
ENTRYPOINT ["pipeline"]
CMD ["run"]
