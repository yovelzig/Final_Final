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

RUN useradd --create-home --uid 1000 finquest \
    && chown -R finquest:finquest /app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

USER finquest
CMD ["uvicorn", "stock_research_core.api.main:app", "--host", "0.0.0.0", "--port", "8080"]

# -- ai: adds the real local sentence-transformer embedding dependency -----------------------------------------------
#
# Deliberately a separate stage, never built by default - `base` (above)
# stays a small, network-free image for API/market/portfolio/evaluation
# workers. Only the knowledge worker (or an API deployment that wants
# real semantic embeddings) needs this stage:
#
#   docker compose build --build-arg TARGET=ai finquest-worker-knowledge
#   (or, equivalently, `docker compose --profile ai build finquest-worker-knowledge`
#   with the `target: ai` override already set on that service below)
FROM base AS ai
USER root
RUN pip install --no-cache-dir ".[ai_tutor]"
USER finquest
CMD ["uvicorn", "stock_research_core.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
