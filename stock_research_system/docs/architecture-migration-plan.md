# FinQuest Architecture Migration Plan

**Stage:** 0 — Baseline, architecture inventory, migration planning (documentation only; no implementation).
**Source of truth:** actual code in `stock_research_system/`, read and verified during this stage — not prior documentation, not file names alone.

This document contains: Owner Migration Decisions (authoritative), §1 method, §2 current-architecture capability map (evidence-based classification), §3 current-to-target gap matrix, §4 baseline risks, §5 proposed target repository structure.

---

## Owner Migration Decisions (Authoritative)

The following decisions were given directly by the product owner during Stage 0 and are **authoritative** — they supersede any conflicting Stage 0 conclusion drawn purely from technical/dependency analysis. In particular, they supersede the earlier n8n audit's "nothing here is obsolete" conclusion (§2.25 below and `deprecation-removal-plan.md` §3): that conclusion assessed technical entanglement (is it wired, tested, referenced?), not product relevance (is it still wanted?). These are two different questions, and decision 4 below makes explicit that only the second one determines what stays.

1. **Existing PostgreSQL production data is not business-critical** and may be reset during a planned migration. This is a materially different constraint than Stage 0's original framing, which treated data preservation as close to inviolable (see the original risk table's "current data-loss risk" entry) — data preservation is no longer a hard requirement. This does **not** mean an immediate reset is authorized now — see decision 6.
2. **Mandatory preservation boundary** (the only hard, non-negotiable infrastructure/network constraints for this entire migration):
   - Current AWS EC2 instance
   - Current Elastic IP and DNS
   - `researchstock.store`
   - `api.researchstock.store`
   - Caddy
   - HTTPS
   - Public Web traffic routed through Caddy to `localhost:3000`
   - Public API traffic routed through Caddy to `localhost:8080`
   - GitHub-based deployment (GitHub `main` as source of truth, manual pull-and-redeploy on EC2)

   Everything else — application code, specific services beyond this list, database schema and content, individual API routes, tests, n8n workflows, diagrams — is in scope for change if it doesn't serve the target architecture.
3. **Existing application code, API routes, database tables, tests, old n8n workflows, diagrams, exports, and documentation may be removed or replaced** when they are not relevant to the target architecture. This is materially broader deletion authority than Stage 0's original conclusion ("no files were identified as safe to delete outright" — `deprecation-removal-plan.md` §"Summary"), which was scoped to technical safety only, not product fit.
4. **The existence of tests or references does not by itself make a feature a product requirement.** A feature being tested, imported, or documented proves it is *technically wired*, not that the product still wants it. Tests for intentionally removed features should be removed or replaced alongside the feature they were protecting — an orphaned test for a deliberately-removed feature is not a reason to keep the feature.
5. **Preserve reusable infrastructure where useful**, explicitly: authentication (identity/JWT/refresh-token subsystem), FastAPI, Next.js, PostgreSQL, pgvector, TimescaleDB, Redis, Celery, Docker, Alembic, the ports/adapters (hexagonal) architecture, and generic secure integration contracts (e.g. the n8n-facing key-hash-auth/idempotency layer in `api/routers/integrations.py`/`integration_auth.py`, which is generic and not n8n-specific — see `architecture-migration-plan.md` §2.25). These are kept regardless of which specific application features built on top of them are removed.
6. **Do not reset the production database yet.** A planned reset is permitted **only after all of the following are validated locally first**: the new schema is defined, migrations for it are written, a bootstrap/seed procedure exists, admin-account recreation is defined, and smoke tests pass locally end-to-end against that new schema. This is a sequencing gate — decision 1 establishes that a reset is *permitted in principle*, decision 6 establishes that it is **not yet authorized in practice**.
7. **Stage 1 is revised** from a conservative, narrowly-scoped cleanup into a **Controlled Structural Reset** — full detail in `migration-status.md`'s revised Stage 1 section. In summary: determine product relevance (not only technical references) for existing code/tests/n8n assets/docs; remove confirmed-obsolete n8n workflows, diagrams, and their corresponding tests; remove confirmed-obsolete application modules and documentation; preserve the reusable generic infrastructure named in decision 5; avoid empty package scaffolding; keep the mandatory preservation boundary (decision 2) unchanged; do not modify production from Claude Code.

**What this pass did and did not do:** this is a documentation-only recording of the above decisions and a re-scoping of Stage 1's plan to reflect them. **No file was deleted, moved, or modified as application code as a result of this pass.** Determining exactly *which* specific n8n workflows, application modules, routes, tables, or docs are "confirmed obsolete" under decisions 3-4 is Stage 1's own first work item — it requires product-relevance judgment this Stage 0 pass does not have the authority or information to make unilaterally, and is explicitly called out as such in the revised Stage 1 plan.

---

## Phase Sequencing Cross-Reference

This document's capability map and gap matrix (§2–§3) remain the authoritative *architecture* analysis. For current *phase sequencing* (A1/A2/B/C1/C2.1–C2.3/F1/C3/D/E/G1/G2/H/I/J), see `migration-status.md`'s "Master-Spec Phase Plan" section — the Stage 0–10 numbering previously cross-referenced from this document is superseded and preserved only as history in that file.

---

## 1. Method

Every capability below was classified by reading the domain/application/infrastructure/API code that implements it, checking whether it is registered in `src/stock_research_core/api/app_factory.py` (the single composition root for the API) or `infrastructure/operations/celery_tasks.py` (the Celery composition root), and cross-referencing existing tests. Classifications used:

`IMPLEMENTED_AND_CONNECTED` · `IMPLEMENTED_BUT_DISABLED` · `IMPLEMENTED_BUT_EMPTY` · `PARTIALLY_IMPLEMENTED` · `TEST_ONLY` · `MOCK_OR_SYNTHETIC` · `OBSOLETE` · `NOT_IMPLEMENTED` · `UNKNOWN_NEEDS_VERIFICATION`

---

## 2. Current-Architecture Capability Map

### 2.1 Identity / Authentication — `IMPLEMENTED_AND_CONNECTED`

Full register/login/refresh/logout/logout-all/me flow. `AccountRole` = `LEARNER | CONTENT_EDITOR | ADMIN` (`domain/identity/enums.py:17-20`). Refresh tokens are opaque, rotated on use, grouped into "families" — reuse of an already-rotated token revokes the whole family (`application/identity/service.py:283-328`). `AccountStatus` = `ACTIVE | LOCKED | DISABLED | PENDING`, with admin enable/disable (`api/routers/admin.py:100-121`). ADMIN and CONTENT_EDITOR are both real, enforced roles (`require_admin`, `require_content_editor` dependencies).
**Files:** `application/identity/*`, `domain/identity/*`, `infrastructure/identity/*`, `api/routers/{auth,admin}.py`, `infrastructure/database/orm/{user_account,account_refresh_token,authentication_audit_event}.py`.
**Tests:** `tests/unit/test_identity_{architecture,domain,security,service}.py`, `test_jwt_access_token_service.py`, `test_opaque_refresh_token_service.py`, `test_argon2_password_hasher.py`, `test_client_identity_resolver.py`, `test_api_authorization.py`; `tests/integration/test_auth_api.py`, `test_admin_api.py`.

### 2.2 Learning / Curriculum — `IMPLEMENTED_AND_CONNECTED`

Hierarchy is **LearningPath → LearningModule → Lesson**, plus a separate **Skill** taxonomy — functionally equivalent to "Course/Track/Unit/Concept" but under different names; no class literally named `Course`, `Track`, or `Concept` exists. Read endpoints in `api/routers/curriculum.py`; authoring (upsert path/module/lesson/exercise) in `api/routers/admin.py:138-248`, gated by `require_content_editor`. `scripts/seed_learning_curriculum.py` (907 lines, idempotent uuid5-keyed) populates one real curriculum ("Investing Foundations": 1 path, 4 modules, 8 lessons, 24 exercises) — content exists, is modest in size.
**Files:** `domain/learning/models.py`, `application/learning/{service,models,ports}.py`, `infrastructure/database/orm/{learning_path,learning_module,lesson,skill}.py`, `api/routers/curriculum.py`.
**Tests:** `tests/unit/test_learning_{domain_models,mappers,service,unit_of_work}.py`; `tests/integration/test_curriculum_{api,repository}.py`.

### 2.3 Exercises / Attempts / Grading — `PARTIALLY_IMPLEMENTED`

Deterministic auto-grading exists for `SINGLE_CHOICE`, `MULTIPLE_CHOICE`, `TRUE_FALSE`, `NUMERIC_INPUT`, `ORDERING` (`application/learning/grading.py:16-38`). `TEXT_RESPONSE` and `SCENARIO_DECISION` are **explicitly documented as never auto-graded** — a genuine, acknowledged gap, not an oversight.
**Files:** `application/learning/grading.py`, `domain/learning/models.py` (`Exercise`, `ExerciseAttempt`, `ExerciseAnswer`), `infrastructure/database/orm/exercise*.py`.
**Tests:** `tests/integration/test_attempt_repository.py`; grading covered indirectly by `test_learning_service.py`.

### 2.4 Mastery + Spaced Repetition — `IMPLEMENTED_AND_CONNECTED`

`DeterministicMasteryCalculator` (`application/learning/mastery.py:73-135`) uses a versioned ("mastery-v1") EMA rule (0.8·previous + 0.2·latest) with 4 mastery levels and per-level review intervals. `SkillReviewSchedule` is a real SM-2-style schedule (ease factor, consecutive successes, next-review date), driven by `DeterministicReviewSchedulingPolicy`.
**Files:** `application/learning/mastery.py`, `application/adaptive_learning/policies.py`, `infrastructure/database/orm/{skill,skill_mastery,skill_review_schedule}.py`.
**Tests:** `tests/unit/test_spaced_repetition_policy.py`; `tests/integration/test_mastery_repository.py`, `test_review_schedule_repository.py`.

### 2.5 Adaptive Learning, Placement/Diagnostics — `IMPLEMENTED_AND_CONNECTED`

Sessions, `AdaptiveDecision` recommendations, and `DiagnosticAssessment`/`DiagnosticAssessmentItem` placement tests are fully modeled with a rich API (`api/routers/adaptive_learning.py`: sessions, decision accept/start/skip/answer, diagnostics start/answer/complete).
**Files:** `application/adaptive_learning/*`, `domain/adaptive_learning/*`, `infrastructure/database/orm/{diagnostic_assessment,diagnostic_assessment_item,exercise_adaptive_profile,adaptive_decision}.py`.
**Tests:** `tests/unit/test_adaptive_*`, `test_diagnostic_policy.py`, `test_difficulty_policy.py`, `test_skill_priority_policy.py`; `tests/integration/test_adaptive_*`, `test_diagnostic_repository.py`.

### 2.6 Misconceptions — `IMPLEMENTED_BUT_EMPTY`

`Misconception` (`domain/learning/models.py:333-362`) is a validated data record with a repository port to store/read rows — but its own module docstring states detection logic is **"out of scope for this phase,"** and no code path in `application/` ever writes a detected misconception. The table and API surface exist; nothing populates them today.
**Files:** `domain/learning/models.py`, `infrastructure/database/orm/misconception.py`, `application/learning/ports.py`.
**Tests:** None specifically targets misconception detection (only storage/shape, indirectly).

### 2.7 Gamification (XP, streaks, achievements) — `IMPLEMENTED_BUT_EMPTY`

`LearnerDashboard.current_streak_days` / `.total_xp` exist as API fields but are **hardcoded to zero** (`application/learning/service.py:336-337`), with the docstring stating explicitly: *"gamification placeholders for a later phase and are always zero for now."* No achievements/badges/leaderboard concept exists anywhere (verified by repo-wide grep for `xp|streak|achievement|gamif|badge|leaderboard`).
**Files:** `application/learning/models.py:51-66`, `application/learning/service.py:300-340`.
**Tests:** None.

### 2.8 Historical Market Scenarios — `IMPLEMENTED_AND_CONNECTED`

Real point-in-time historical decision scenarios (list/view/start/submit/reveal), graded by `RuleBasedScenarioGradingPolicy`, computed by `PandasScenarioCalculator`. `scripts/seed_historical_market_scenarios.py` (638 lines, idempotent) seeds the catalog.
**Files:** `application/market_scenarios/*`, `domain/market_scenarios/*`, `infrastructure/market_scenarios/pandas_scenario_calculator.py`, `api/routers/market_scenarios.py`.
**Tests:** `tests/unit/test_market_scenario_*`, `test_scenario_calculator.py`, `test_scenario_grading_policy.py`; `tests/integration/test_market_scenario*`, `test_scenario_*_repository.py`.

### 2.9 Market Data — `IMPLEMENTED_AND_CONNECTED` (real) + `MOCK_OR_SYNTHETIC` (test fixture, correctly scoped)

`YFinanceMarketDataAdapter` (`infrastructure/market_data/yfinance_adapter.py:39-264`) calls real `yfinance.Ticker(...).history(...)` with data-quality checks — genuine external data, not mocked. Wired to `BackgroundJobType.TRACKED_MARKET_REFRESH`/`SECURITY_MARKET_REFRESH` → real Celery tasks. Separately, `scripts/seed_e2e_synthetic_market_data.py` inserts deterministic synthetic OHLCV bars for two fixture tickers (`E2ETEST`, `E2EBENCH`) so Playwright doesn't need network access — clearly scoped to test/demo use, never called from a production code path.
**Files:** `application/market_data/*`, `infrastructure/market_data/yfinance_adapter.py`, `scripts/seed_e2e_synthetic_market_data.py`.
**Tests:** `tests/test_market_data_service.py`, `test_yfinance_adapter.py`, `test_yfinance_resolver.py` (top-level `tests/`, not `unit`/`integration`).

### 2.10 Virtual Portfolio + Decision Journal — `IMPLEMENTED_AND_CONNECTED`

Full paper-trading feature: create portfolio, preview/execute trades (idempotency-key-protected), list holdings/transactions, record and list decision-journal entries (trade-attached and standalone), request/view valuations and performance feedback.
**Files:** `application/virtual_portfolio/*`, `domain/virtual_portfolio/*`, `infrastructure/virtual_portfolio/pandas_portfolio_analytics.py`, `api/routers/virtual_portfolios.py`. Wired to `BackgroundJobType.PORTFOLIO_VALUATION`/`PORTFOLIO_BATCH_VALUATION` → real Celery tasks.
**Tests:** `tests/unit/test_portfolio_*`, `test_virtual_portfolio_*`; `tests/integration/test_portfolio_*`, `test_virtual_portfolio*`.

### 2.11 AI Tutor / Grounded RAG pipeline — `IMPLEMENTED_AND_CONNECTED`

`GroundedAITutorService.ask()` (`application/ai_tutor/service.py:131-375`) is a genuinely wired end-to-end flow: persist message → input guardrail (refuse/fallback/allow) → hybrid retrieval → prompt build → model generate → output guardrail validate → one bounded retry → fallback-to-insufficient-evidence if still invalid → persist answer + citations, log knowledge gap on fallback. Not a stub.
**Files:** `application/ai_tutor/{service,lesson_tutor,scenario_tutor,portfolio_tutor,prompt_builder,retrieval,guardrails,ports,models}.py`, `api/routers/ai_tutor.py`.
**Tests:** `tests/unit/test_ai_tutor_*`, `test_tutor_guardrails.py`, `test_tutor_prompt_builder.py`, `test_hybrid_retrieval_policy.py`; `tests/integration/test_ai_tutor_*`, `test_hybrid_retrieval.py`, `test_knowledge_ingestion_duplicate_content.py`.

### 2.12 Heading-Aware Chunking — `IMPLEMENTED_AND_CONNECTED`

`HeadingAwareWordChunker` (`application/ai_tutor/chunking.py:27-179`) — real, deterministic: splits on heading-style lines, groups into ~350-word (max 450) chunks with 50-word overlap, computes a SHA-256 `content_hash` per chunk. No ML dependency.
**Tests:** `tests/unit/test_document_chunker.py`.

### 2.13 Embeddings — `IMPLEMENTED_AND_CONNECTED` (production) + `TEST_ONLY` (fake adapter, correctly gated)

`SentenceTransformerEmbeddingAdapter` is the **default** (`EmbeddingSettings.embedding_provider = "sentence_transformer"`), lazily imports `sentence_transformers`, real `model.encode(normalize_embeddings=True)` off-loop via `asyncio.to_thread`. `DeterministicFakeEmbeddingAdapter` is explicitly "TEST-ONLY/DEVELOPMENT-ONLY" and is **blocked in production** by `assert_embedding_provider_production_safe()` (`infrastructure/ai_tutor/production_safety.py:26-44`) unless `ALLOW_FAKE_EMBEDDINGS_IN_PRODUCTION=true` is explicitly set — a real, enforced safety gate, called from `app_factory.create_app()` whenever `testing=False`.
**Files:** `infrastructure/ai_tutor/{sentence_transformer_embeddings,deterministic_fake_embeddings,production_safety,config}.py`.
**Tests:** `tests/unit/test_embedding_port.py`.

### 2.14 pgvector + Hybrid Retrieval — `IMPLEMENTED_AND_CONNECTED`

`migrations/versions/0006_grounded_ai_tutor.py` enables `CREATE EXTENSION IF NOT EXISTS vector`, defines `Vector(384)` embeddings with an **HNSW** index (`vector_cosine_ops`), plus a custom `knowledge_chunk_tsvector(...)` SQL function (GIN-indexed) for the lexical side. `HybridKnowledgeRetriever` + `SqlAlchemyKnowledgeRepository.hybrid_search` (`infrastructure/database/repositories/knowledge_repository.py:358-434+`) fuse pgvector cosine-distance search with PostgreSQL full-text search (`ts_rank_cd`) — **"hybrid" = vector + Postgres full-text, not an external BM25/Elasticsearch engine.**
**Tests:** `tests/unit/test_hybrid_retrieval_policy.py`; `tests/integration/test_hybrid_retrieval.py`, `test_knowledge_repository.py`, `test_pgvector_extension.py`.

### 2.15 Local LLM (Ollama) Generation — `REUSABLE_GENERIC_ADAPTER_EXISTS / OLLAMA_NOT_INTEGRATED`

**Ollama itself is not classified as implemented.** What exists is a **generic** OpenAI-compatible HTTP tutor adapter that happens to be reusable against Ollama's own OpenAI-compatible endpoint — the distinction matters because no Ollama-specific integration work has actually happened yet:

- `TutorModelSettings.tutor_model_provider` **defaults to `"extractive"`** (`infrastructure/ai_tutor/config.py:38`), mapped by `app_factory._build_tutor_model()` to `DeterministicExtractiveTutor` — a keyword-overlap sentence extractor, no LLM call, no network access. This is the provider actually running today in every environment that hasn't overridden the setting.
- Setting `TUTOR_MODEL_PROVIDER=openai_compatible` switches to `OpenAICompatibleTutorAdapter` (`infrastructure/ai_tutor/openai_compatible_tutor.py`) — a **generic** OpenAI-compatible chat-completions HTTP client (retry logic, one bounded structured-output repair attempt, strict citation-shape validation). It contains no Ollama-specific code, no Ollama model name hardcoded, and no Ollama-specific error handling.
- Its default `tutor_model_base_url = "http://localhost:11434/v1"` merely **points at** Ollama's conventional default port and `/v1` surface — a configuration default, not evidence of integration. **No Ollama model is configured anywhere in this repository, and no Ollama service exists in either Compose file** (confirmed in `current-architecture-inventory.md` §3).
- **No Ollama-specific health check, lifecycle management, concurrency test, or integration test exists.** `tests/unit/test_extractive_tutor.py` covers only the default extractive provider; no test, unit or integration, exercises `OpenAICompatibleTutorAdapter` against a real or mocked Ollama endpoint at all.

**What this means for Stage 4:** the lift is smaller than "implement Ollama from scratch" (the generic HTTP client, retry/repair logic, and citation-shape validation are already written and reusable), but it is not "Ollama is done and just needs enabling" either. Stage 4 must still: stand up an actual Ollama deployment, choose and configure a specific model, write the missing Ollama-facing health/lifecycle/concurrency/integration tests, and only then consider flipping the default in target environments.
**Files:** `infrastructure/ai_tutor/{openai_compatible_tutor,extractive_tutor,config}.py`.
**Tests:** `tests/unit/test_extractive_tutor.py`. No test currently exercises `OpenAICompatibleTutorAdapter` against a real or mocked Ollama endpoint — a gap to close before relying on it in Stage 4.

### 2.16 Guardrails (input/output) — `IMPLEMENTED_AND_CONNECTED`; retrieval-stage guardrail — folded into retriever, not separate

`RuleBasedTutorGuardrail` (`application/ai_tutor/guardrails.py`) is real deterministic regex/keyword logic: input guardrail detects scenario-future-info leakage, guaranteed-return claims, buy/sell instructions, personalized-allocation requests, off-topic messages; output guardrail re-checks the model's own answer for invalid citations, guaranteed-return/buy-sell language, scenario/portfolio leakage, unverified URLs, hidden-reasoning markers → `GroundingStatus`. Every decision is persisted (`orm/tutor_guardrail_decision.py`). There is **no separate "retrieval guardrail" module** — the closest analog (the exercise-answer leakage filter) lives inside `retrieval.py`.
**Tests:** `tests/unit/test_tutor_guardrails.py`; `tests/integration/test_guardrail_repository.py`.

### 2.17 Document Versioning / Hash / Approval Workflow — `PARTIALLY_IMPLEMENTED`

`KnowledgeDocument` has a SHA-256 `content_hash`, `document_version`, `approval_status` (`DRAFT|APPROVED|REJECTED|ARCHIVED`), and a uniqueness constraint. Versioning is "supersede-and-archive" (changed content → new content-derived row, old one archived), not an append-only version-history table. Retrieval enforces `approval_status == APPROVED`. `cli/knowledge_base.py` can set approval status **at ingestion time only** — **no `approve_document`/post-hoc transition method or endpoint exists anywhere** (verified by repo-wide grep) — there is no way to move a DRAFT document to APPROVED after ingestion except manual DB edit or re-ingesting.
**Files:** `orm/knowledge_document.py`, `domain/ai_tutor/enums.py`, `application/ai_tutor/knowledge_ingestion.py`, `infrastructure/database/repositories/knowledge_repository.py`, `cli/knowledge_base.py`.

### 2.18 Knowledge Sufficiency Gate — `NOT_IMPLEMENTED`

No module/class/docstring named "sufficiency gate" exists anywhere (verified by grep). Today's sufficiency logic is implicit and binary: "no candidates → fallback" (`service.py:189`) and "no cited chunks → INSUFFICIENT_EVIDENCE" (`guardrails.py`). No confidence/relevance-score threshold, no minimum-candidate-count check, no dedicated port/class. This is a genuine build-from-scratch item for the target architecture, though it can integrate at the existing `GroundingStatus.INSUFFICIENT_EVIDENCE` fallback point rather than requiring new plumbing.

### 2.19 Markdown Seed Documents — `PARTIALLY_IMPLEMENTED`

The **ingestion pipeline** for standalone Markdown/PDF/DOCX files is real (`local_document_parsers.py`, `KnowledgeIngestionService.ingest_local_document()`, exposed via CLI). But `scripts/seed_finquest_knowledge_base.py` populates the knowledge base **exclusively from already-stored curriculum lesson/exercise text**, not from a curated Markdown corpus — and **no standalone Markdown knowledge-content directory exists in the repo today** (`docs/` holds only the 3 project/migration docs, not tutor content). `evaluation/suites/*.jsonl` contain evaluation *cases* (assert the tutor's answer covers required concepts), not knowledge content — they presuppose curriculum-derived content already covers those topics.

### 2.20 Citation Production and Verification — `IMPLEMENTED_AND_CONNECTED`

`quoted_excerpt` is guaranteed to be a literal substring of actual chunk content (never model-invented); the output guardrail separately verifies every model-cited chunk ID was actually retrieved (`INVALID_CITATION_CHUNK_ID`). `tutor_retrieval_runs`/`tutor_retrieval_run_chunks` audit every retrieval query. Citations persist only for `VALIDATED` answers, never `REFUSED`/`FALLBACK`.
**Files:** `orm/{tutor_answer_citation,tutor_retrieval_run,tutor_knowledge_gap}.py`.

### 2.21 Quality Evaluation / RAGAS — Deterministic path `IMPLEMENTED_AND_CONNECTED`; RAGAS-specific path `IMPLEMENTED_BUT_DISABLED` by default

`application/quality_evaluation/*` is a substantial real application layer (datasets, deterministic metrics, learning metrics, regression, reports, runner). `RagasEvaluationAdapter` genuinely drives `ragas==0.4.3` (pinned together with `langchain-community==0.3.31` specifically so `import ragas` succeeds — see `pyproject.toml:58-66` comment). Feature flag `ragas_enabled: bool = False` (default) means a deployment never even imports `ragas` unless explicitly turned on; deterministic metrics run regardless. API fully wired at `/api/v1/admin/evaluations`.
**Tests:** `tests/unit/test_ragas_adapter.py`, `test_quality_evaluation_domain.py`; `tests/integration/test_quality_evaluation_*`.

### 2.22 LangGraph Learning Orchestrator ("Coach") — `IMPLEMENTED_BUT_DISABLED`

**Real LangGraph**, not hand-rolled: `application/learning_orchestrator/graph_builder.py` imports `langgraph.graph.{StateGraph,START,END}`, builds a 22-node graph, compiles with a real checkpointer. `infrastructure/learning_orchestrator/graph_runtime.py` drives it via genuine `ainvoke`/`astream(stream_mode="updates")`/`Command(resume=...)` (interrupt/resume human-in-the-loop pattern). SSE streaming (`/threads/{id}/runs/stream`, `/runs/{id}/resume/stream`) and Postgres checkpointing (real `langgraph.checkpoint.postgres.aio.AsyncPostgresSaver`) are both implemented, not stubbed.
**Gate:** `LangGraphSettings.langgraph_enabled: bool = False` — when off, no checkpointer pool opens, no graph compiles, and **`/api/v1/coach` is not even registered** (`app_factory.py:245,406-407`). `docker-compose.yml` sets `LANGGRAPH_ENABLED: ${LANGGRAPH_ENABLED:-false}`. This matches `docs/migration-status.md`'s pre-existing note that LangGraph is "disabled" in the current deployment plan.
**Tests:** Unit tests use in-memory fakes (`tests/unit/learning_orchestrator_fakes.py`, explicitly "no PostgreSQL, Redis, LangGraph checkpointer, or model provider" required); integration tests (`tests/integration/test_orchestrator_*`, `test_langgraph_postgres_checkpointer.py`) exercise the **real** `StateGraph`/`AsyncPostgresSaver` against a live test database.

### 2.23 Celery / Background Jobs / Redis — `IMPLEMENTED_AND_CONNECTED`

13 tasks across 5 queues (`finquest.{default,market,portfolio,knowledge,evaluation}`), 4 dedicated worker containers, no beat/Flower (scheduling is intentionally external, via n8n). Redis serves both as Celery broker/result-backend and as a distributed lock (`RedisDistributedLock`) — two independent uses of one instance. See [current-architecture-inventory.md](current-architecture-inventory.md) §8 for the full task table.

### 2.24 Observability (metrics, tracing, structured logging) — `IMPLEMENTED_AND_CONNECTED`, disabled-by-default sub-features

`PrometheusMetrics` is instantiated and served at a real `GET /metrics` (gated by `metrics_enabled`, optionally `require_admin`). OpenTelemetry tracing (`build_tracing`) is wired in but `otel_enabled: bool = False` by default. `structlog` structured logging is configured in both the API lifespan and the Celery worker process. None of this is dead code; the OTel piece is simply off by default.

### 2.25 n8n Integration — `IMPLEMENTED_AND_CONNECTED` (backend contract) + genuinely absent deployment

Confirmed: **n8n is not deployed anywhere** (no `n8n` string in `Dockerfile` or either compose file). The generic integration API (`api/routers/integrations.py`, registered **unconditionally**, unlike LangGraph) is real and DB-backed: idempotent job submission, replay protection via `integration_requests`, key-id/hashed-key auth (`integration_auth.py`), readiness check. This surface authenticates *any* automation client, not n8n specifically. The 6 exported n8n workflow JSON files are well-formed, tested (`tests/integration/test_n8n_workflow_contracts.py` — structural/security-shape contract, always runs, no DB needed), and reference only the FinQuest API — no other external dependency. See §5 (n8n audit is in the dedicated file below, duplicated in short form here for completeness) and [deprecation-removal-plan.md](deprecation-removal-plan.md) for the file-by-file disposition.
**Full dedicated n8n audit:** see §6 below (kept in this file per the Stage 0 task list requiring it in the architecture-migration-plan; a condensed cross-reference also appears in [deprecation-removal-plan.md](deprecation-removal-plan.md)).

### 2.26 Bilingual (English/Hebrew) and RTL Support — `NOT_IMPLEMENTED`

**Backend:** `LearnerProfile.preferred_language` is a stored, unvalidated free-text field (default `"en"`), never read by any translation/localization logic. No i18n/RTL machinery exists in `src/`.
**Frontend:** root layout hardcodes `<html lang="en">` with no `dir` attribute anywhere. The Settings page's "Preferred language" field is `PATCH`-persisted but nothing reads it back to change rendered language or text direction — a stored-but-inert preference. No Hebrew content, no RTL CSS, no locale files exist.
**Classification:** `NOT_IMPLEMENTED` end-to-end; the one existing field is best described as `IMPLEMENTED_BUT_EMPTY` (stored, never consumed).

### 2.27 Frontend — routes, auth, learning, tutor/coach, portfolio, scenarios, admin, evaluations

All `IMPLEMENTED_AND_CONNECTED`. Full detail (route-by-route, hook-by-hook) is in [current-architecture-inventory.md](current-architecture-inventory.md) §11 and was independently verified against real backend routes (no inline mock data found in production route/component code; MSW mocks exist only under `frontend/tests/mocks/`). Notable specifics:
- **Auth**: in-memory-only access token (never localStorage), HttpOnly `SameSite=strict` refresh cookie, single-flight refresh-on-401 — correctly mirrors the backend's JWT + opaque-refresh-token + family-revocation model.
- **Coach vs. Tutor**: two distinct chat surfaces matching two distinct backend routers — Coach is real authenticated-fetch SSE (not `EventSource`, since that can't carry an `Authorization` header) against `/api/v1/coach/...`; Tutor is non-streaming request/response against `/api/v1/tutor/...`. Both render citations; only learner-safe citation fields are ever exposed client-side.
- **Admin**: narrow in scope — only `admin/evaluations` exists; no user/content-management admin UI (backend admin capability for those exists but has no frontend surface yet).
- **Test pyramid**: real, layered (unit → component → integration(MSW) → accessibility(jest-axe) → e2e(Playwright+axe-playwright)) — not a token test suite.

---

## 3. Current-to-Target Gap Matrix

Legend for **Production risk**: 🟢 low · 🟡 medium · 🔴 high.

### 3.1 Learning Engine

| Target capability | Existing implementation | Existing file paths | Reusable as-is | Requires extension | Requires replacement | Missing | DB impact | API impact | Frontend impact | Prod risk | Recommended stage |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Course | `LearningPath` | `domain/learning/models.py`, `orm/learning_path.py` | ✅ (rename optional, not required) | — | — | — | none if kept as-is | none | none | 🟢 | 9 |
| Track | `LearningModule` | `domain/learning/models.py`, `orm/learning_module.py` | ✅ | — | — | — | none | none | none | 🟢 | 9 |
| Unit | *(no separate concept — Module≈Unit today)* | — | partial | new tier between Module and Lesson if needed | — | Unit as distinct tier | new table+migration if introduced | new endpoints | new UI | 🟡 | 9 |
| Lesson | `Lesson` | `orm/lesson.py` | ✅ | — | — | — | none | none | none | 🟢 | 9 |
| Concept | *(none — Skill is the closest analog, coarser-grained)* | `orm/skill.py` | partial | extend Skill or add Concept as sub-tier | — | dedicated Concept modeling | new table+migration | new endpoints | new UI | 🟡 | 9 |
| Exercise | `Exercise`, 5 auto-graded types | `application/learning/grading.py` | ✅ for graded types | grading for `TEXT_RESPONSE`/`SCENARIO_DECISION` | — | free-text/scenario grading rubric | none (columns exist) | extend grading endpoint | minor | 🟡 | 9 |
| Versioning (curriculum) | none found for Path/Module/Lesson (only KB docs are versioned) | — | — | add version field/history | — | curriculum content versioning | new migration | new endpoints | minor | 🟡 | 9 |
| Placement assessment | `DiagnosticAssessment`/`Item` | `application/adaptive_learning/*` | ✅ | — | — | — | none | none | none | 🟢 | done (reuse) |
| Mastery | `DeterministicMasteryCalculator`, EMA + levels | `application/learning/mastery.py` | ✅ | — | — | — | none | none | none | 🟢 | done (reuse) |
| Misconceptions | data model + repo, no detector | `domain/learning/models.py:333-362` | model reusable | write a detection service | — | detection logic itself | none | new write path | new UI (already has read UI hooks?) | 🟡 | 9 |
| Spaced repetition | `SkillReviewSchedule`, SM-2-style | `orm/skill_review_schedule.py` | ✅ | — | — | — | none | none | none | 🟢 | done (reuse) |
| Gamification (XP/streaks/achievements) | hardcoded zero fields only | `application/learning/service.py:336-337` | field shape reusable | implement real computation | — | achievements/badges/leaderboard entirely | new tables for achievements | extend dashboard endpoint | new UI | 🟢 | 9 |
| Bilingual (EN/HE) | `preferred_language` field, unused | `domain/learning/models.py:49` | field reusable | wire to real i18n | — | translation content, RTL rendering, locale infra | possibly new content tables (localized strings) | new/extended endpoints | major (RTL layout, i18n strings) | 🟡 | 9 |

### 3.2 Knowledge / Tutor Engine

| Target capability | Existing implementation | Existing file paths | Reusable as-is | Requires extension | Requires replacement | Missing | DB impact | API impact | Frontend impact | Prod risk | Recommended stage |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Markdown seed documents | ingestion pipeline only, no corpus | `application/ai_tutor/knowledge_ingestion.py`, `infrastructure/ai_tutor/local_document_parsers.py` | pipeline ✅ | author + ingest real corpus | — | the actual 15 documents | new `KnowledgeDocument`/`Chunk` rows (data only) | none (ingestion CLI exists) | none | 🟢 | 3 |
| YAML front matter / manifest | not present | — | — | build front-matter parser + manifest schema | — | entirely | none | new ingestion validation step | none | 🟢 | 3 |
| SHA-256 validation | exists (per-document, per-chunk) | `orm/knowledge_document.py`, `chunking.py` | ✅ | — | — | — | none | none | none | 🟢 | done (reuse) |
| Object storage (S3-compatible) | not present — local file parsing only | `infrastructure/ai_tutor/local_document_parsers.py` | parser reusable | add S3 adapter behind existing port | — | S3 adapter itself | none (documents stored as text, not raw files, today) | none | none | 🟡 | 3 |
| Document versions | supersede-and-archive, not append-history | `orm/knowledge_document.py` | ✅ as designed | optional: add explicit version-chain if audit trail required | — | — | optional new column | none | none | 🟢 | 3 |
| Approval workflow | field + ingestion-time set only | `domain/ai_tutor/enums.py`, `cli/knowledge_base.py` | field ✅ | add `approve_document` transition (service+endpoint) | — | post-hoc approval action | none | new admin endpoint | new admin UI | 🟡 | 3 |
| Chunking | heading-aware, real | `application/ai_tutor/chunking.py` | ✅ | — | — | — | none | none | none | 🟢 | done (reuse) |
| Embeddings | SentenceTransformer, real, production-gated | `infrastructure/ai_tutor/sentence_transformer_embeddings.py` | ✅ | — | — | — | none | none | none | 🟢 | done (reuse); kept through Stage 4 per target's own instruction |
| pgvector | HNSW index, real | `migrations/versions/0006_grounded_ai_tutor.py` | ✅ | — | — | — | none | none | none | 🟢 | done (reuse) |
| Hybrid retrieval | vector + Postgres full-text | `infrastructure/database/repositories/knowledge_repository.py` | ✅ | — | — | — | none | none | none | 🟢 | done (reuse) |
| Sufficiency gate | implicit binary check only | `application/ai_tutor/service.py:189`, `guardrails.py` | fallback plumbing reusable | build a named, scored gate on top | — | scored/threshold-based gate | none | none | none | 🟡 | 5 |
| Ollama | `REUSABLE_GENERIC_ADAPTER_EXISTS / OLLAMA_NOT_INTEGRATED` — generic OpenAI-compatible adapter exists, not default, no Ollama-specific health/lifecycle/concurrency/integration test exists, no Ollama model configured, `TUTOR_MODEL_PROVIDER` defaults to `extractive` | `infrastructure/ai_tutor/openai_compatible_tutor.py` | ✅ (generic HTTP client, retry, citation validation) | add Ollama-specific health/lifecycle/concurrency/integration tests; flip default in target environments | — | actual Ollama deployment + model configuration | none | none | none | 🟡 | 4 |
| Citation validation | real, end-to-end | `application/ai_tutor/service.py`, `guardrails.py` | ✅ | — | — | — | none | none | none | 🟢 | done (reuse) |
| Guardrails (input/output) | real | `application/ai_tutor/guardrails.py` | ✅ | add distinct retrieval-stage guardrail if desired | — | dedicated retrieval guardrail component | none | none | none | 🟢 | 5 |

### 3.3 Live Research Engine

| Target capability | Existing implementation | Existing file paths | Reusable as-is | Requires extension | Requires replacement | Missing | DB impact | API impact | Frontend impact | Prod risk | Recommended stage |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Current-information classification | none | — | — | — | — | entirely | new | new | none yet | 🟢 | 7 |
| Research jobs | `BackgroundJob`/Celery infra generic, not research-specific | `application/operations/*`, `infrastructure/operations/celery_tasks.py` | job infra ✅ | add a `LIVE_RESEARCH` job type reusing `BackgroundJobService` | — | research-specific job payload/result models | new tables | new endpoints | new UI | 🟡 | 7 |
| Normalized evidence | none | — | — | — | — | entirely | new tables | new | new | 🟢 | 7 |
| n8n | workflows real, tested, not deployed; generic integration API real and unconditionally wired | `n8n/workflows/*.json`, `api/routers/integrations.py` | integration contract ✅ | rewrite/extend workflows for new job types once Stage 7/8 design is set | — | actual n8n deployment | none (schema already supports arbitrary `BackgroundJobType`) | none (generic) | none | 🟡 | 8 |
| Perplexity | none | — | — | — | — | entirely | none yet | new adapter behind existing `TutorModelPort`-style port pattern | none | 🟢 | 8 |
| SEC / official filings | none | — | — | — | — | entirely | new tables | new | new | 🟢 | 8 |
| Structured market data providers | yfinance only | `infrastructure/market_data/yfinance_adapter.py` | ✅ as one provider | add additional provider adapters behind existing `MarketDataProviderPort` | — | additional providers | none | none | none | 🟢 | 8 |
| Research callbacks | generic integration callback pattern exists (`GET /jobs/{id}/events`) | `api/routers/integrations.py` | pattern reusable | extend for research-specific event types | — | research-specific events | none | new event types | new UI | 🟡 | 7-8 |
| Source scoring / contradiction handling | none | — | — | — | — | entirely | new | new | new | 🟢 | 7 |
| Citation verification (research) | tutor-side pattern exists and is reusable conceptually | `application/ai_tutor/guardrails.py` (pattern) | pattern reusable, not the code itself | build analogous verification for research sources | — | research-specific verification | new | new | new | 🟡 | 7 |
| Research synthesis | LangGraph orchestrator exists as a pattern (not research-specific) | `application/learning_orchestrator/*` | orchestration pattern reusable | add a Live Research subgraph analogous to existing subgraphs | — | research synthesis logic itself | new | new | new | 🟡 | 7 |

### 3.4 Cross-Cutting

| Target capability | Existing implementation | Reusable as-is | Requires extension | Requires replacement | Missing | Prod risk | Recommended stage |
|---|---|---|---|---|---|---|---|
| Docker / production Compose | 8 services, identical names local vs. prod, no beat/Flower; worker health contracts and base/ai image targets corrected in Phase A2 (`finquest-api`/`finquest-worker-knowledge` on `ai`, `finquest-worker-market`/`-portfolio`/`-default` on `base`, knowledge-only `--require-embedding` healthcheck) | ✅ | — | — | — | 🟢 | A2 (done) |
| Configuration | pydantic-settings throughout, consistent pattern, feature flags default-safe | ✅ | — | — | — | 🟢 | ongoing |
| Security | Argon2, opaque refresh + family revocation, security headers middleware, correlation IDs | ✅ | — | — | — | 🟢 | ongoing |
| Observability | Prometheus + OTel (opt-in) + structlog, all real | ✅ | enable OTel by default in later stage if desired | — | — | 🟢 | ongoing |
| Tests | 1165 backend unit + 64 integration files + 154 frontend tests, layered pyramid both sides | ✅ | add tests for Ollama-real-endpoint path, misconception detection once built | — | ruff/mypy/black/CI entirely absent | 🟡 (no CI gate today) | 1 (tooling), ongoing |
| Documentation | this Stage 0 set + extensive README | ✅ | keep in sync as stages land | — | — | 🟢 | ongoing |
| Deployment | manual EC2 git-pull + compose, documented | ✅ pattern | see runbook | — | — | 🟡 | ongoing |
| Backup and restore | Phase A2 added `scripts/backup_production_database.sh` (verified `pg_dump -F c` → temp file → `pg_restore --list` verify → atomic rename) and a documented restore command in the runbook; syntax-validated locally, **not yet executed/verified on the real EC2 database** | ✅ helper exists | — | — | full automated retention/off-server pipeline + a real restore drill | 🟡 (until exercised on EC2) | A2 (helper, done); 10 (automation + drill) |

---

## 4. Baseline Risks

| Risk | Likelihood | Impact | Evidence | Mitigation | Stage to address |
|---|---|---|---|---|---|
| Architectural — renaming domain concepts (Path→Course, Module→Track) breaks a large, well-tested surface for cosmetic reasons | Medium | Medium | 168KB README and 1165+ tests reference current names throughout | Prefer additive aliasing/documentation mapping over renaming; only rename with a proven need (per user's own instruction) | 9 |
| Database migration — 11-migration linear chain is currently clean; any Stage 1+ migration must not break `alembic upgrade head` idempotency | Low today | High if broken | `README.md:380-386` states `0001` is idempotent by design; other migrations not independently re-verified for idempotency in this stage | Test every new migration with upgrade+downgrade+upgrade against a throwaway DB before merging | every stage touching schema |
| Package-renaming — instruction against renaming `stock_research_core` without proven need | Low (no plan proposes this) | High if done anyway | 300+ files import `stock_research_core.*` | Do not rename; use internal module reorganization only | 1 |
| Deletion risk — nothing in this repo was found to be safely deletable without further reference analysis (see `deprecation-removal-plan.md`) | Low | Medium | Every "obsolete-looking" file this stage inspected (n8n assets, backups) turned out to be either tested, documented, or a legitimate rollback copy | No deletions in Stage 0; Stage 1 deletions require the validation steps in `deprecation-removal-plan.md` | 1 |
| API compatibility — `/api/v1/coach` OpenAPI snapshot test already drifted from actual surface | Confirmed (already happened) | Low (test-only, not a runtime break) | `tests/unit/test_openapi_snapshot.py` 2 failures, see `current-architecture-inventory.md` §12.1 | Update the snapshot deliberately in the stage that intentionally changes the coach API, not silently | 6 (or whenever coach surface next changes) |
| Frontend compatibility — OpenAPI-generated `types/generated-api.ts` must stay in sync with backend schema | Medium (manual step, `api:check` script exists but wasn't run this stage) | Medium | `frontend/package.json` scripts `api:export`/`api:generate`/`api:check` | Run `npm run api:check` in CI or pre-merge once CI exists | 1 (tooling), then ongoing |
| Embedding-version risk — changing `EMBEDDING_MODEL_NAME`/dimension invalidates all existing vectors silently unless re-embedding is run | Medium (real risk once real content is ingested at scale) | High | `EMBEDDING_DIMENSION=384` hardcoded to the current model; `knowledge_reembed` Celery task exists for exactly this | Always re-embed after any embedding-provider/model change; never assume old vectors are compatible | 3, 4 |
| Ollama resource risk — no evidence yet of memory/CPU sizing for local LLM inference on the EC2 host | Medium | Medium (could destabilize the shared host) | Current EC2 host also runs Postgres/Redis/4 workers/API/web — sizing unknown from repo alone | Size/benchmark Ollama on a non-production host first; make it opt-in via existing flag before flipping default | 4 |
| Current EC2 resource risk — adding LangGraph (checkpointer pool) + RAGAS + Ollama simultaneously without capacity planning | Medium | High | All three are real, connected-but-disabled features that each add memory/CPU/DB-connection load when enabled | Enable one at a time, each behind its existing flag, monitoring `/metrics` before/after | 4, 5, 6 |
| n8n migration risk — Stage 7/8 rework may need to change the 5 job-trigger workflow contracts | Low today | Medium | Workflows are tested and stable; risk only appears once Live Research introduces new job types the workflows don't yet know about | Extend, don't replace, the polling/idempotency pattern already proven in `test_n8n_workflow_contracts.py` | 7, 8 |
| LangGraph migration risk — enabling `LANGGRAPH_ENABLED=true` in production for the first time is an untested-in-production code path (though integration-tested locally) | Medium | Medium | Feature flag has never been flipped on in the deployed environment per `migration-status.md`'s known-limitations note | Stage 6 should include a canary/staging-style enablement plan, not a direct production flip | 6 |
| Current data-loss risk — no automated backup routine exists yet, independent of this migration | Unknown (not verifiable from repo alone) | High | Runbook already *requires* a verified manual backup before every migration/data transformation (see `production-deployment-runbook.md` §5) — but no automation exists today, and this document does not claim otherwise | Stage 2 defines/adds a repeatable backup helper/runbook command (must exist and be exercised before Stage 3's ingestion); a full automated retention/off-server pipeline and restore drill remain Stage 10's scope | 2 (helper), 10 (automation + drill), manual backup required at every schema-touching stage in the meantime |
| Security — `METRICS_REQUIRE_AUTH` and admin-gated endpoints depend on correct env configuration in production | Low | Medium | Code correctly supports the gate; misconfiguration is an operational risk, not a code defect | Document required production env values (names only) in the runbook; verify via smoke test after deploy | ongoing |
| Financial-safety — guardrails already forbid guaranteed-return claims and specific buy/sell instructions | Low (already mitigated) | High if regressed | `application/ai_tutor/guardrails.py` (both input and output checks) | Any tutor/generation change must re-run `test_tutor_guardrails.py` and the `finquest-safety-v1`/`finquest-scenario-safety-v1` evaluation suites | 4, 5 |
| Source-verification risk — Live Research has no source-scoring/contradiction-handling yet | High (unbuilt) | High (a wrong "current" fact is worse than an honest abstention) | Confirmed `NOT_IMPLEMENTED` in §3.3 | Build source scoring and contradiction handling before enabling any live-research answer path publicly | 7 |
| Bilingual-content risk — Hebrew/RTL is fully unbuilt; retrofitting late is expensive | Medium | Medium | Confirmed `NOT_IMPLEMENTED` end-to-end, both backend and frontend | Decide on an i18n strategy (e.g. `next-intl` + backend localized-content tables) before Stage 9 starts, not during it | 9 |
| No CI / no lint / no type-check gate today | Confirmed | Medium (defects can land undetected) | No `.github/` workflows; `ruff`/`mypy`/`black` not installed or configured | **Stage 1 CI proposal** (not yet built, not yet run): a workflow running `pytest tests/unit -q` (the exact command Stage 0 executed — 1165 passed, 2 pre-existing failures) plus frontend `lint`/`typecheck`/`test`. `pytest -m "not integration"` is a broader marker-based invocation that was **not** the command Stage 0 ran and is not yet verified to produce the same result (it would also collect the 4 loose top-level test files under `tests/`, which `pytest tests/unit -q` does not) — Stage 1 should decide and verify which invocation CI uses, not assume they're equivalent | 1 |

---

## 5. Proposed Target Repository Structure

Guiding constraint from the user: **do not rename `stock_research_core`** without a proven technical reason (none was found), and prefer gradual internal restructuring over a destructive rewrite. The hexagonal layering already in place (`domain/ → application/ → infrastructure/ ← api/`, `cli/`) is sound and matches the target architecture's own vocabulary (ports, adapters) closely enough that any future reorganization should happen *within* it, not replace it.

**Sequencing note (per explicit correction to this plan):** the tree below is a **target end-state proposal**, not a Stage 1 task list. In particular, splitting `domain/ai_tutor/`, `application/ai_tutor/`, and `infrastructure/ai_tutor/` into `knowledge/`/`tutor/` packages must **not** happen until a later stage that both (a) has an actual new capability that needs the split (e.g., Stage 3's Markdown corpus work, or Stage 5's sufficiency gate) and (b) has a complete dependency plan for the move, verified against `migration-dependency-map.md` §9 (which already enumerates every consumer that would need updating: `app_factory.py` imports, the LangGraph `graph_builder.py`/`nodes.py`/`subgraphs.py` consumers, `cli/ai_tutor.py`, `cli/knowledge_base.py`, and every `test_ai_tutor_*` import). Stage 1 does **not** create any of the packages shown below, empty or otherwise — see `migration-status.md`'s Stage 1 scope, which was revised specifically to exclude this.

```
stock_research_system/
├── src/stock_research_core/            # KEEP root package name
│   ├── domain/
│   │   ├── learning/                   # KEEP — Path/Module/Lesson/Skill/Exercise
│   │   ├── knowledge/                  # NEW — rename target for today's ai_tutor domain models
│   │   │                               #   that are really "knowledge base" concerns
│   │   │                               #   (KnowledgeDocument, KnowledgeChunk, approval enums)
│   │   ├── tutor/                      # NEW — split from ai_tutor: conversation/answer/
│   │   │                               #   citation/guardrail-decision models only
│   │   ├── live_research/              # NEW — research job/evidence/source domain models
│   │   ├── adaptive_learning/          # KEEP
│   │   ├── identity/                   # KEEP
│   │   ├── market_scenarios/           # KEEP
│   │   ├── virtual_portfolio/          # KEEP
│   │   ├── operations/                 # KEEP
│   │   ├── quality_evaluation/         # KEEP
│   │   └── learning_orchestrator/      # KEEP — becomes the top-level LangGraph domain;
│   │                                   #   Stage 6 adds live_research as a sibling subgraph,
│   │                                   #   not a replacement
│   ├── application/                    # mirrors domain/ split above 1:1 (same subpackage names)
│   │   ├── knowledge/                  # NEW — ingestion, chunking, versioning, approval workflow
│   │   │                               #   (moved/renamed from today's ai_tutor/{chunking,
│   │   │                               #   knowledge_ingestion}.py; a thin compatibility
│   │   │                               #   re-export can live in ai_tutor/ during migration)
│   │   ├── tutor/                      # NEW — service/prompt_builder/retrieval/guardrails
│   │   │                               #   (moved from today's ai_tutor/*; retrieval.py gains
│   │   │                               #   a distinct sufficiency-gate port)
│   │   ├── live_research/              # NEW — job orchestration, evidence normalization,
│   │   │                               #   source scoring, synthesis — built in Stage 7
│   │   └── ...                         # all other current subpackages KEEP as-is
│   ├── infrastructure/
│   │   ├── knowledge/                  # NEW — S3/object-storage adapter, Markdown/YAML
│   │   │                               #   front-matter parser (extends today's
│   │   │                               #   local_document_parsers.py)
│   │   ├── tutor/
│   │   │   ├── ollama/                 # NEW — thin subclass/config profile of today's
│   │   │   │                           #   OpenAICompatibleTutorAdapter, defaulting to Ollama
│   │   │   └── ...                     # (moved from ai_tutor/*)
│   │   ├── live_research/
│   │   │   ├── n8n/                    # NEW home for n8n-facing adapters — today's
│   │   │   │                           #   integration_auth.py, integration client/request
│   │   │   │                           #   repos MOVE here once Stage 7/8 need them
│   │   │   │                           #   co-located with research-specific code
│   │   │   ├── perplexity/             # NEW — Stage 8
│   │   │   └── sec/                    # NEW — Stage 8
│   │   ├── market_data/                # KEEP — yfinance adapter; new providers become
│   │   │                               #   siblings here (Stage 8), same port
│   │   └── ...                         # all other current subpackages KEEP as-is
│   ├── api/
│   │   ├── routers/                    # KEEP flat structure; add live_research.py (Stage 7)
│   │   ├── transport/                  # NEW — factor the SSE helpers currently embedded in
│   │   │                               #   learning_orchestrator.py into a shared module,
│   │   │                               #   since Live Research will need SSE too
│   │   └── ...
│   ├── contracts/                      # KEEP — cross-cutting ports; add live_research ports here
│   └── cli/                            # KEEP flat structure; add live_research_admin.py (Stage 7)
├── docs/                                # KEEP — project/migration documentation only (this
│                                       #   Stage 0 set); tutor content does NOT live here
├── knowledge/                          # NEW — the approved Markdown seed corpus, distinct
│   └── seed_documents/                 #   from docs/ (Stage 3 deliverable)
│       ├── en/                         #   *.md documents with front matter
│       └── manifest.json               #   per-document SHA-256 hashes + metadata
├── n8n/                                # KEEP location; workflows revised in place at Stage 8,
│                                       #   not moved — `infrastructure/live_research/n8n/`
│                                       #   holds the *code* that talks to n8n, this directory
│                                       #   remains the *workflow export* location
├── evaluation/                         # KEEP — add live_research and knowledge-corpus suites
├── migrations/                         # KEEP — strictly additive, one revision per stage
├── scripts/                            # KEEP — add corpus-validation script (Stage 3)
├── tests/                              # KEEP structure (unit/integration); mirror new
│                                       #   knowledge/, tutor/, live_research/ subpackages
├── frontend/                           # KEEP structure; add live_research UI (Stage 7) and
│                                       #   i18n/RTL infrastructure (Stage 9) additively
└── docker-compose*.yml                 # KEEP service names; add an `ollama` service (Stage 4)
                                       #   and, later, an `n8n` service only if self-hosting
                                       #   it becomes part of the deployment (Stage 8 decision)
```

**Compatibility measures during migration:** wherever `application/ai_tutor/*` is split into `application/knowledge/*` and `application/tutor/*`, keep `application/ai_tutor/__init__.py` re-exporting the moved names for at least one full stage after the move, so any code (tests, scripts, CLI) not yet updated keeps working. The same applies to `infrastructure/ai_tutor/*`. This is exactly the "internal restructuring over destructive rename" principle applied consistently.

No change to `stock_research_core` as the root package name is proposed anywhere in this structure — every reorganization above happens *inside* it.
