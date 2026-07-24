# FinQuest — Current Architecture Inventory (Stage 0 Baseline)

**Status:** Stage 0 — Baseline, inventory, and safety documentation.
**Scope:** Read-only inventory of the repository as it exists today. No application code, migration, dependency, or Docker configuration was changed to produce this document.

---

## 1. Git Baseline

| Item | Value |
|---|---|
| Branch | `migration/stage-00-baseline` |
| Commit SHA | `c1f9e2240594cb237a1d13abab042fcece7bf04f` |
| Working-tree status at start of Stage 0 | Clean except untracked `stock_research_system/docs/{architecture-migration-plan.md, migration-status.md, production-deployment-runbook.md}` (empty/stub placeholders created before this session) |
| Remote `origin` | `https://github.com/yovelzig/Final_Final.git` |
| Other local branches | `main` (identical history at the time of Stage 0; no divergent commits found) |

No secrets or `.env` values are recorded anywhere in this document or its siblings.

---

## 2. Toolchain Versions Expected by the Project

| Component | Expected | Evidence |
|---|---|---|
| Python (backend) | `>=3.11` | `pyproject.toml:9` (`requires-python = ">=3.11"`) |
| Python (local `.venv` observed) | 3.12.0 | `.venv/Scripts/python.exe --version` |
| Node.js (frontend) | `>=20` | `frontend/package.json` → `"engines": {"node": ">=20"}` |
| Node.js (local, observed) | v24.18.0 | `node --version` |
| Key backend deps (non-exhaustive) | `fastapi>=0.115`, `sqlalchemy>=2.0`, `alembic>=1.13`, `pgvector>=0.3`, `celery[redis]>=5.4`, `langgraph>=1.0`, `langgraph-checkpoint-postgres>=3.0`, `psycopg[binary,pool]>=3.2`, `structlog>=24`, `prometheus-client>=0.20` | `pyproject.toml:10-35` — all core, not optional |
| Optional backend extras | `dev` (pytest), `ai_tutor` (`sentence-transformers>=3`), `langsmith`, `otel` (OpenTelemetry), `quality_evaluation` (`ragas==0.4.3`, `langchain-community==0.3.31` pinned together, `openai>=1`) | `pyproject.toml:37-69` |
| Key frontend deps | `next@^15.1.0`, `react@^19.0.0`, `@tanstack/react-query@^5.62.0`, `zod@^3.24.0`, `react-markdown@^9.0.1`, `recharts@^2.15.0` | `frontend/package.json` |
| Frontend dev/test deps | `vitest@^2.1.8`, `@playwright/test@^1.49.0`, `msw@^2.7.0`, `jest-axe@^9.0.0`, `@axe-core/playwright@^4.10.0`, `typescript@^5.7.0`, `eslint@^9.17.0`, `openapi-typescript@^7.5.0` | `frontend/package.json` |

**Important:** `langgraph` and its Postgres checkpoint package are **core, non-optional** backend dependencies today — LangGraph is already installed in every environment, it is simply feature-flagged off by default at runtime (see [architecture-migration-plan.md](architecture-migration-plan.md)).

---

## 3. Docker Compose Files

| File | Purpose |
|---|---|
| `docker-compose.yml` | Local development stack |
| `docker-compose.yml.backup` | Backup of a prior local compose revision. **Tracked in git** (confirmed via `git ls-files --error-unmatch stock_research_system/docker-compose.yml.backup`, which exits 0 and lists the path — committed in the initial commit). See `deprecation-removal-plan.md` §4 for the full disposition. |
| `docker-compose.production.yml` | Production stack (the one deployed to EC2) |

**Local Compose services** (`docker-compose.yml`): `stock-db`, `redis`, `finquest-api`, `finquest-web`, `finquest-worker-market`, `finquest-worker-portfolio`, `finquest-worker-knowledge`, `finquest-worker-default`.

**Production Compose services** (`docker-compose.production.yml`): identical service names — `stock-db`, `redis`, `finquest-api`, `finquest-web`, `finquest-worker-market`, `finquest-worker-portfolio`, `finquest-worker-knowledge`, `finquest-worker-default`.

`n8n` is **not** a service in either compose file (confirmed by direct grep — no `n8n` string in `Dockerfile`, `docker-compose.yml`, or `docker-compose.production.yml`). There is no `celery beat` service and no Flower service in either file — background-job scheduling is intentionally external (n8n, per `n8n/README.md`), not a cron-in-container.

Local dev Postgres: `timescale/timescaledb:2.17.2-pg16`, service `stock-db`, host port `5433` → container `5432`, database `stock_research`, plus an auto-created `stock_research_test` database (via `scripts/init_test_db.sql` mounted as a Postgres init script) used only by integration tests.

---

## 4. Top-Level Repository Tree

```
Final_Final/
├── .claude/
├── .git/
└── stock_research_system/        (single application directory)
```

## 5. Application Tree (`stock_research_system/`)

```
stock_research_system/
├── .env / .env.backup / .env.example / .env.production.example   (values not inspected/recorded here)
├── Dockerfile
├── alembic.ini
├── docker-compose.yml, docker-compose.production.yml, docker-compose.yml.backup
├── README.md                     (168 KB — extensive, phase-by-phase project log)
├── docs/                         (this Stage 0 documentation set)
├── evaluation/
│   ├── README.md
│   ├── generated/.gitkeep
│   └── suites/                   5 JSON/JSONL evaluation suites (RAG, safety, coach, portfolio, scenario)
├── examples/
│   └── sample_analysis_request.json
├── frontend/                     Next.js 15 / React 19 app (see §11)
├── migrations/                   Alembic — 11 linear revisions (see §6)
├── n8n/                          README, credentials doc, 2 trigger scripts, 6 workflow JSON exports
├── scripts/                      10 operational/seed scripts (see §9)
├── src/stock_research_core/      Python package root (hexagonal architecture — see below)
└── tests/                        149 test files (85 unit, 64 integration, plus 4 loose top-level) (see §10)
```

`src/stock_research_core/` layout (package `stock-research-core`, `pyproject.toml` `[tool.setuptools.packages.find] where = ["src"]`):

```
src/stock_research_core/
├── api/                  FastAPI app_factory, routers/, schemas/, settings, middleware
├── application/          use-case services + ports, one subpackage per capability:
│                         adaptive_learning, ai_tutor, identity, learning,
│                         learning_orchestrator, market_data, market_scenarios,
│                         operations, persistence, quality_evaluation, virtual_portfolio
├── cli/                  14 Typer/Click CLI modules (see §9)
├── contracts/            cross-cutting port protocols
├── domain/                pure domain models/enums, mirroring the application subpackages
└── infrastructure/       SQLAlchemy ORM + repositories, adapters (ai_tutor, identity,
                          market_data, market_scenarios, operations, quality_evaluation,
                          security, virtual_portfolio), database engine/config
```

Full per-file capability mapping (identity, learning, AI Tutor, LangGraph, Celery, n8n, etc.) with exact paths is in [architecture-migration-plan.md](architecture-migration-plan.md) §2 (evidence-based classification) — not duplicated here to avoid drift between two copies of the same fact.

---

## 6. Alembic Migration State

| Item | Value |
|---|---|
| Head revision (in repo) | `0011_ragas_learning_quality` |
| Chain shape | Single linear chain, no branches (`down_revision` of each file points to exactly one predecessor; confirmed by reading `revision`/`down_revision` in all 11 files) |
| Head revision (applied to local dev DB) | `0011_ragas_learning_quality` — **matches repo head** (`alembic current` against local `stock-db`, 2026-07-24) |
| Migration count | 11 |

| # | Revision | down_revision | Subject |
|---|---|---|---|
| 1 | `0001_initial_schema` | — | Initial schema, TimescaleDB extension, market_bars hypertable |
| 2 | `0002_learning_core` | 0001 | Learning path/module/lesson/exercise core |
| 3 | `0003_adaptive_learning` | 0002 | Adaptive learning, diagnostics, mastery, misconceptions |
| 4 | `0004_historical_market_scenarios` | 0003 | Historical market scenario tables |
| 5 | `0005_virtual_portfolios` | 0004 | Virtual portfolio, holdings, transactions, journal |
| 6 | `0006_grounded_ai_tutor` | 0005 | pgvector extension, knowledge documents/chunks/embeddings, HNSW index, tutor tables |
| 7 | `0007_product_api_auth` | 0006 | Identity/auth tables |
| 8 | `0008_kb_doc_context_uniqueness` | 0007 | Context-scoped uniqueness constraint on knowledge documents |
| 9 | `0009_operations_and_n8n` | 0008 | Background jobs, integration clients/requests (n8n-facing) |
| 10 | `0010_langgraph_learning_orchestrator` | 0009 | LangGraph orchestrator audit tables (revision id literally `0010_langgraph_orchestrator`) |
| 11 | `0011_ragas_learning_quality` | 0010 | RAGAS/quality-evaluation, learning-quality aggregation tables |

No unreleased/dangling migrations were found. Per the Stage 0 non-destructive rule, none of these files were modified and no new migration was created.

---

## 7. Docker Compose Service Names (Local vs. Production)

Identical in both files today: `stock-db`, `redis`, `finquest-api`, `finquest-web`, `finquest-worker-market`, `finquest-worker-portfolio`, `finquest-worker-knowledge`, `finquest-worker-default`. This is a good migration property — Stage 1+ should preserve these names unless a stage explicitly justifies a rename.

## 8. Celery Queues and Worker Types

| Queue | Consuming worker(s) | Concurrency |
|---|---|---|
| `finquest.default` | `finquest-worker-default` | 2 |
| `finquest.market` | `finquest-worker-market` | 2 |
| `finquest.portfolio` | `finquest-worker-portfolio` | 4 |
| `finquest.knowledge`, `finquest.evaluation` | `finquest-worker-knowledge` (both queues) | 1 |

Broker: Redis db 0 (`CELERY_BROKER_URL=redis://redis:6379/0`). Result backend: Redis db 1. Redis is also used independently for distributed locking (`infrastructure/operations/redis_lock.py`, Lua-script owner-safe lock) — a second, unrelated use of the same Redis instance. No `celery beat`, no Flower in either compose file.

13 Celery tasks are registered (`infrastructure/operations/celery_tasks.py`): `finquest.tracked_market_refresh`, `finquest.security_market_refresh`, `finquest.portfolio_valuation`, `finquest.portfolio_batch_valuation`, `finquest.curriculum_knowledge_refresh`, `finquest.local_document_ingestion`, `finquest.knowledge_reembed`, `finquest.retrieval_evaluation`, `finquest.knowledge_gap_summary`, `finquest.system_maintenance`, `finquest.ragas_quality_evaluation`, `finquest.learning_quality_aggregation`, `finquest.quality_baseline_comparison`.

## 9. CLI Modules and Scripts

| CLI module (`src/stock_research_core/cli/`) | Purpose |
|---|---|
| `adaptive_learning.py` | Adaptive learning engine operations |
| `ai_tutor.py` | Grounded AI tutor operations |
| `database_status.py` | Connection/migration state, row counts |
| `identity_admin.py` | Identity subsystem admin |
| `ingest_and_store.py` | Ingest market data and persist |
| `knowledge_base.py` | Tutor knowledge-base ingestion/approval-status setting |
| `learning_orchestrator_admin.py` | LangGraph orchestrator admin, incl. `--setup-checkpointer` |
| `learning_status.py` | Learning platform status/curriculum counts |
| `market_data.py` | Manual security resolution / market-data ingestion |
| `market_scenarios.py` | Historical market-scenario engine |
| `operations_admin.py` | Create/list/revoke n8n integration clients; create/status/requeue jobs |
| `quality_evaluation_admin.py` | Quality-evaluation platform admin |
| `virtual_portfolio.py` | Virtual portfolio / decision-journal operations |
| `worker_status.py` | Docker-healthcheck-style worker readiness (DB, Redis, broker, registry, queues) |

| Script (`scripts/`) | Purpose |
|---|---|
| `evaluate_tutor_retrieval.py` | Standalone retrieval-quality evaluation |
| `export_openapi.py` | Exports backend OpenAPI spec (consumed by `frontend`'s `api:export`/`api:generate`) |
| `init_test_db.sql` | Postgres init script creating `stock_research_test` |
| `seed_adaptive_learning_profiles.py` | Seeds adaptive-learning fixture profiles |
| `seed_e2e_synthetic_market_data.py` | Synthetic OHLCV bars for 2 fixture tickers, Playwright-only |
| `seed_finquest_knowledge_base.py` | Ingests curriculum lessons/exercises into the knowledge base |
| `seed_historical_market_scenarios.py` | Seeds historical scenario catalog (638 lines) |
| `seed_learning_curriculum.py` | Seeds "Investing Foundations" curriculum (907 lines, idempotent uuid5-keyed) |
| `seed_quality_evaluation_fixtures.py` | Seeds quality-evaluation suite fixtures |
| `wait_for_database.py` | Polls Postgres readiness (used in local setup and CI-style flows) |

## 10. Backend API Routers Registered (`api/app_factory.py`)

Unconditional (registered regardless of any feature flag): `health`, `auth` (`/api/v1/auth`), `learners`, `curriculum`, `adaptive_learning` (`/api/v1/adaptive`), `market_scenarios` (`/api/v1/scenarios`), `virtual_portfolios` (`/api/v1/portfolios`), `ai_tutor` (`/api/v1/tutor`), `admin` (`/api/v1/admin`), `operations` (`/api/v1/operations`), `quality_evaluation` (`/api/v1/admin/evaluations`), `integrations` (`/api/v1/integrations/n8n`).

Conditional: `learning_orchestrator` (`/api/v1/coach`) — **only registered when `LANGGRAPH_ENABLED=true`** (`app_factory.py:406-407`); otherwise the route family does not exist at all, not merely disabled.

Also present: unversioned `GET /metrics` (Prometheus, gated by `METRICS_ENABLED`, optionally `METRICS_REQUIRE_AUTH`).

## 11. Frontend Routes (Next.js App Router)

| Segment | Routes |
|---|---|
| `app/(auth)/` | `login/page.tsx`, `register/page.tsx` |
| `app/(protected)/` | `dashboard`, `learn`, `learn/[pathId]`, `lessons/[lessonId]`, `practice`, `diagnostic`, `portfolios`, `portfolios/new`, `portfolios/[portfolioId]`, `portfolios/[portfolioId]/journal`, `portfolios/[portfolioId]/trade`, `scenarios`, `scenarios/[scenarioId]`, `coach`, `coach/[threadId]`, `tutor`, `tutor/[conversationId]`, `admin/evaluations`, `admin/evaluations/[runId]`, `settings` |
| `app/api/` (Route Handlers) | `auth/login`, `auth/register`, `auth/logout`, `auth/session`, `auth/refresh` |
| `app/healthz/` | liveness probe route |
| Top-level | `layout.tsx`, `page.tsx` (marketing/landing), `error.tsx`, `not-found.tsx` |

All routes read real data via TanStack Query hooks against the FastAPI backend; no inline mock data was found in production route code (confirmed independently in this Stage 0 investigation).

---

## 12. Baseline Test Inventory and Results

All commands below were **executed** during Stage 0 against the local repository and local Docker containers only. No production infrastructure was touched. Durations are wall-clock from the actual runs.

### 12.1 Backend

| Command | Environment prerequisite | Result | Passed | Failed | Skipped | Duration |
|---|---|---|---|---|---|---|
| `.venv/Scripts/python.exe -m pytest tests/unit -q` | None (no DB/Redis) | **2 failed, 1165 passed** | 1165 | 2 | 0 | 51.35s |
| `.venv/Scripts/python.exe -m pytest tests/integration -m integration -q` | Local `stock-db` (Postgres/TimescaleDB) + local `redis` running, migrated to head | **Not completed to full pass/fail count — see §12.3** | — | — | — | not completed |

**Command scope note:** `pytest tests/unit -q` targets only the `tests/unit/` directory. It does **not** collect the 4 loose top-level test files (`tests/test_market_data_service.py`, `test_models.py`, `test_yfinance_adapter.py`, `test_yfinance_resolver.py`, discussed in `deprecation-removal-plan.md` §8) — those were not executed in this Stage 0 run. This is distinct from `pytest -m "not integration"`, which (per `pyproject.toml`'s `testpaths = ["tests"]`) would also collect those 4 files and everything else under `tests/` not marked `integration`; that broader invocation was **not** run in Stage 0 and its result is not claimed here.

**Backend lint/type-check/format**: `pyproject.toml` defines **no** `[tool.ruff]`, `[tool.black]`, `[tool.mypy]`, or equivalent sections, and none of `ruff`, `mypy`, `black` are installed in `.venv` (`pip show ruff mypy black` → "Package(s) not found"). **There is no official formatting, linting, or type-checking command configured for the Python backend today** — this is a real gap, not a Stage 0 omission. No `.github/` CI workflows exist in the repository (confirmed: `find .github -type f` → nothing), so there is no CI-defined command to fall back to either.

**Unit test failures (both pre-existing, not introduced by Stage 0):**

1. `tests/unit/test_openapi_snapshot.py::test_openapi_path_surface_matches_the_expected_contract` — fails because the OpenAPI snapshot's expected-path allowlist has not been updated for the 10 `/api/v1/coach/...` LangGraph-orchestrator paths that now exist in the generated spec. The test's own assertion message names the drift explicitly: `undocumented new paths - update this snapshot deliberately: ['/api/v1/coach/runs/{run_id}', ...]`.
2. `tests/unit/test_openapi_snapshot.py::test_openapi_tags_match_the_expected_contract` — same root cause: actual tag set includes `'Learning Coach'`, not yet added to the test's expected-tag allowlist.

Both are a **test-fixture drift issue** (the LangGraph coach router was added to the app but the hand-maintained OpenAPI snapshot test wasn't updated alongside it), not an application defect. Per the Stage 0 non-destructive rule, this was **not fixed** — fixing it would mean editing a test file's expectations, which is itself a judgment call about desired API surface, appropriately deferred to a later stage.

### 12.2 Frontend

| Command | Result | Passed | Failed | Duration |
|---|---|---|---|---|
| `npm run typecheck` (`tsc --noEmit`) | **Clean** — no output, exit 0 | — | 0 | — |
| `npm run lint` (`eslint .`) | **Clean** — no output, exit 0 | — | 0 | — |
| `npm run test` (`vitest run` — covers `tests/unit`, `tests/component`, `tests/integration`, `tests/accessibility`) | **34 test files, 154 tests, all passed** | 154 | 0 | 74.95s |

No frontend build (`npm run build`) or Playwright e2e (`npm run test:e2e`) was run in Stage 0: `build` was judged unnecessary to validate a documentation-only stage and risks a long-lived `.next/standalone` artifact; `test:e2e` requires the full stack (API + workers + seeded data) running simultaneously, which was already the case locally (see §12.4) but was intentionally not exercised in Stage 0 to avoid mutating any seeded/dev data as a side effect of a documentation task. Both are safe, low-risk commands to run explicitly in Stage 1.

Frontend test output included benign React Testing Library `act()` warnings (`AuthProvider`, router link updates) and Recharts `width(0)/height(0)` container-size warnings under jsdom — both are known jsdom-environment artifacts, not failures, and did not affect pass/fail counts.

### 12.3 Integration test run — honest account

The full `pytest tests/integration -m integration` run was **attempted twice and not completed** within Stage 0's practical time budget — this is reported honestly rather than as a pass/fail count, per the instruction not to claim a test passed unless it was executed to completion.

What was actually observed:

1. **First attempt** (all 64 integration files, no exclusions): produced no output for a long period. Misread as a hang (low CPU usage on the pytest process) and manually stopped — in hindsight this was very likely a misdiagnosis: `pytest -q` fully buffers stdout when not attached to a TTY, so zero visible output does not mean zero progress, and integration tests are I/O-bound against Postgres, so low CPU usage is expected and normal, not a hang signal. Stopping this run was a Stage 0 process error, corrected below.
2. **Sanity check**: `pytest tests/integration/test_health_api.py tests/integration/test_auth_api.py -m integration -q` — **ran to completion: 20 passed, 0 failed, 46.01s.** This confirms the local integration harness (migrated `stock-db`, `redis`, `.venv`) works correctly end-to-end; there is no environment-level defect.
3. **Second attempt** (all integration files except `test_job_concurrency.py`, `test_orchestrator_concurrency.py`, `test_orchestrator_sse_cancellation.py`, `test_portfolio_concurrency.py`, `test_langgraph_postgres_checkpointer.py` — excluded because they are inherently slow/concurrency-timing-oriented, not because they were suspected broken): ran for roughly 20 minutes, reached 27 tests with **zero failures observed** (all `.` in the live progress output, no `F`), before being deliberately stopped to keep Stage 0 within a reasonable time budget rather than let a single command run for an unbounded number of hours. **27/27 is not reported as a final count** — it is a partial, in-progress observation, not a completed run, and the true file/test that was next in progress was not captured.

**Root cause of the slowness (not a defect, an expected cost):** several integration files load and run the real `sentence-transformers` model (`test_hybrid_retrieval.py`, `test_ai_tutor_end_to_end.py`, `test_knowledge_ingestion_duplicate_content.py`, etc. — per `EmbeddingSettings.embedding_provider = "sentence_transformer"` being the real default) and/or compile and execute real LangGraph graphs (`test_orchestrator_*`), both of which are legitimately much slower per-test than simple repository CRUD tests. At the observed rate, a full run is estimated to take well over an hour — this was not budgeted for in Stage 0 and should be run as a dedicated CI job (Stage 1 recommendation) with a multi-hour timeout, not as an interactive command.

**What this means for Stage 0's conclusions:** none of the architecture classifications in `architecture-migration-plan.md` depend on the full integration suite passing — those classifications were made from reading code and from the unit-test run (complete) plus this partial, zero-failure-observed integration sample. No integration test failure was observed at any point in either attempt.

### 12.4 Migration / Compose validation

| Command | Result |
|---|---|
| `alembic current` (against local dev DB) | `0011_ragas_learning_quality (head)` — DB is at repo head, no drift |
| `docker compose config` | Not run in Stage 0 (see Known Unknowns in the final response) — recommended as a Stage 1 pre-flight check |

### 12.5 Local environment state observed

At the time of Stage 0 testing, the user's local Docker Desktop already had a **full local stack running** (not started by this session, and not production): `finquest-web`, `finquest-api`, all 4 worker containers, `stock-db`, `finquest-redis` — all reported `healthy`, up 30–33 hours. This is local development infrastructure only; the production EC2 host was never contacted, connected to, or referenced by any command in this stage.

---

## 13. Environment Variables (Names Only — No Values Recorded)

`.env.example` and `.env.production.example` exist and were not opened for values in this document (Stage 0 rule: no secrets or `.env` values recorded). Settings classes reading them: `ApiSettings`/`AuthSettings` (`api/settings.py`), `DatabaseSettings` (`infrastructure/database/config.py`), `EmbeddingSettings`/`TutorModelSettings` (`infrastructure/ai_tutor/config.py`), `OperationsSettings`/`ProxySettings` (`infrastructure/operations/config.py`), `LangGraphSettings` (`infrastructure/learning_orchestrator/config.py`), `quality_evaluation` config (`infrastructure/quality_evaluation/config.py`). All are `pydantic-settings` `BaseSettings` subclasses reading `env_file=".env"` — importing any of these modules never has a side effect (repeatedly documented in their own docstrings).
