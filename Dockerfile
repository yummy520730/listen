FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMBA_NUM_THREADS=1 \
    NUMBA_CACHE_DIR=/tmp/numba \
    LINGYIN_DATA_DIR=/data

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install .

RUN useradd --create-home --uid 10001 lingyin \
    && mkdir -p /data /tmp/numba \
    && chown -R lingyin:lingyin /app /data /tmp/numba

USER lingyin

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl --fail "http://127.0.0.1:${PORT:-8080}/healthz" || exit 1

CMD ["python", "-m", "lingyin_server"]
