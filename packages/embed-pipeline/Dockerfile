# ---------------------------------------------------------------------------
# embed-pipeline — Ray worker image
#
# Built with a multi-stage approach:
#   builder  — installs Python deps into /install
#   runtime  — lean image with only what's needed to run
#
# Build args:
#   PROVIDER  — which embed-core extras to install (default: clip)
#               options: clip | sentence_transformers | bedrock | openai
# ---------------------------------------------------------------------------

ARG PYTHON_VERSION=3.11
ARG PROVIDER=clip

# ---- builder ---------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ARG PROVIDER

WORKDIR /build

# System build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
    && rm -rf /var/lib/apt/lists/*

# Install pip tools
RUN pip install --no-cache-dir hatchling

# Copy and install embed-core with requested provider extras
COPY packages/embed-core ./embed-core
RUN pip install --no-cache-dir --prefix=/install \
        "./embed-core[${PROVIDER}]"

# Copy and install embed-pipeline
COPY packages/embed-pipeline ./embed-pipeline
RUN pip install --no-cache-dir --prefix=/install \
        "./embed-pipeline"

# ---- runtime ---------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ARG PROVIDER

LABEL org.opencontainers.image.title="embed-pipeline"
LABEL org.opencontainers.image.description="Ray-based parallel embedding pipeline"

# Runtime system deps (libgomp for PyTorch, libGL for Pillow)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

# Non-root user
RUN useradd --no-create-home --shell /bin/false pipeline
USER pipeline

WORKDIR /app

# Entrypoint — Ray job submits this module
ENTRYPOINT ["python", "-m", "embed_pipeline.main"]
