# FinQuest API - production ASGI process.
#
# Migrations are NOT run automatically by this image's entrypoint - run
# them explicitly after the container is up:
#
#   docker compose exec finquest-api python -m alembic upgrade head
#
# This keeps schema changes an explicit, reviewable operator action
# rather than something that silently happens on every container start.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System dependencies: build tools for any source-built wheels
# (e.g. argon2-cffi), plus a CA bundle for outbound HTTPS (market-data
# providers, OpenAI-compatible tutor endpoints, if configured).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini

RUN pip install --no-cache-dir .

COPY scripts ./scripts

# Version-controlled, approved seed-knowledge corpus (Phase C1-C3) -
# read-only application content, not a writable volume. Required for
# `cli.knowledge_base --ingest-manifest` to find
# knowledge/seed_documents/manifest.json inside the container.
COPY knowledge ./knowledge

RUN useradd --create-home --uid 1000 finquest \
    && chown -R finquest:finquest /app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

USER finquest
CMD ["uvicorn", "stock_research_core.api.main:app", "--host", "0.0.0.0", "--port", "8080"]

# -- ai: adds the real local sentence-transformer embedding dependency -----------------------------------------------
#
# Deliberately a separate stage - `base` (above) stays a small,
# network-free image with no `sentence-transformers`/torch. Production
# builds `finquest-api` and `finquest-worker-knowledge` on this `ai`
# stage (the API process and the only worker whose queues -
# finquest.knowledge / finquest.evaluation - ever call an embedding
# provider); `finquest-worker-market`, `finquest-worker-portfolio`, and
# `finquest-worker-default` build on `base`, since none of their job
# handlers touch embeddings (see docker-compose.production.yml).
#
# CPU-only PyTorch, pinned and explicit: the production EC2 host is
# CPU-only, but `pip install sentence-transformers` alone resolves an
# unpinned torch build from PyPI's default index, which today means the
# CUDA/NVIDIA-bundled wheel (~9GB of nvidia-*/triton packages this host
# can never use). Installing a pinned `+cpu` wheel from PyTorch's own CPU
# index *before* `.[ai_tutor]` satisfies sentence-transformers' torch
# requirement without ever resolving the CUDA build.
FROM base AS ai
USER root
RUN pip install --no-cache-dir torch==2.13.0+cpu --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir ".[ai_tutor]"
USER finquest
CMD ["uvicorn", "stock_research_core.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
