# ---------------------------------------------------------------------------
# embed-api — FastAPI search service image
#
# Build arg:
#   PROVIDER  — which embed-core extras to install (default: clip)
# ---------------------------------------------------------------------------

ARG PYTHON_VERSION=3.11
ARG PROVIDER=clip

FROM python:${PYTHON_VERSION}-slim AS builder

ARG PROVIDER

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir hatchling

COPY packages/embed-core ./embed-core
RUN pip install --no-cache-dir --prefix=/install \
        "./embed-core[${PROVIDER}]"

COPY packages/embed-api ./embed-api
RUN pip install --no-cache-dir --prefix=/install \
        "./embed-api"

# ---- runtime ---------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ARG PROVIDER

LABEL org.opencontainers.image.title="embed-api"
LABEL org.opencontainers.image.description="FastAPI vector similarity search service"

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

RUN useradd --no-create-home --shell /bin/false api
USER api

WORKDIR /app

EXPOSE 8080

CMD ["uvicorn", "embed_api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
