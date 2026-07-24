# FinQuest Migration Dependency Map

**Stage:** 0 — documentation only. This map exists so that no future deletion or move is approved solely because a file "looks unused." Every dependency below is backed by an actual import, test reference, Docker/Compose reference, or documented composition root found during Stage 0.

---

## 1. Composition Roots (where wiring decisions actually happen)

There are exactly three places in this repository where concrete infrastructure is instantiated and connected — everything else is a pure port/service that only these roots assemble:

1. **`src/stock_research_core/api/app_factory.py`** — the API composition root. `create_app()`'s `lifespan` builds every adapter (DB engine, embedding provider, tutor model, Redis client, Celery client, metrics, tracing, and — conditionally — the entire LangGraph orchestrator stack) and `include_router()` calls wire every router. **Any capability not reachable from this file, directly or via a flag it checks, is not live in the API process.**
2. **`src/stock_research_core/infrastructure/operations/celery_tasks.py`** + **`registry_factory.py`** — the worker composition root. `build_operations_registry()` maps each `BackgroundJobType` to a concrete handler; `_make_task()` generates the actual Celery task functions from that registry.
3. **Each `src/stock_research_core/cli/*.py` module** — one composition root per CLI command; each constructs only the adapters it needs directly (not through `app_factory.py`).

A file that is imported only by tests, or only by another file with no path back to one of these three roots, is a legitimate `TEST_ONLY` or dead-code candidate — but per Stage 0 findings, no such file was identified (see `deprecation-removal-plan.md`).

---

## 2. API Router → Application Service → Repository → ORM Table dependency chains

| Router | Application service(s) | Repository port(s) | ORM table(s) | Registered unconditionally? |
|---|---|---|---|---|
| `auth.router` | `application/identity/service.py` | `UserAccountRepository`, `RefreshTokenRepository`, `AuthenticationAuditRepository` | `user_accounts`, `account_refresh_tokens`, `authentication_audit_events` | Yes |
| `admin.router` | `application/identity/service.py`, `application/learning/service.py` | same as above + curriculum repos | + `learning_paths`, `learning_modules`, `lessons`, `exercises` | Yes |
| `curriculum.router` | `application/learning/service.py` | `CurriculumRepository`, `AttemptRepository` | `learning_paths`, `learning_modules`, `lessons`, `exercises`, `exercise_attempts`, `exercise_answers` | Yes |
| `adaptive_learning.router` | `application/adaptive_learning/service.py` | `AdaptiveDecisionRepository`, `AdaptiveProfileRepository`, `DiagnosticRepository`, `MasteryRepository`, `ReviewScheduleRepository` | `adaptive_decisions`, `exercise_adaptive_profiles`, `diagnostic_assessments(_items)`, `skill_mastery`, `skill_review_schedules` | Yes |
| `market_scenarios.router` | `application/market_scenarios/service.py` | `MarketScenarioRepository`, `ScenarioSubmissionRepository`, `ScenarioOutcomeRepository`, `ScenarioRubricRepository`, `ScenarioGenerationRunRepository` | `historical_market_scenarios` + 4 related tables | Yes |
| `virtual_portfolios.router` | `application/virtual_portfolio/{service,valuation_service}.py` | `VirtualPortfolioRepository`, `PortfolioHoldingRepository`, `PortfolioTransactionRepository`, `PortfolioJournalRepository`, `PortfolioValuationRepository`, `PortfolioRiskRepository` | `virtual_portfolios` + 6 related tables | Yes |
| `ai_tutor.router` | `application/ai_tutor/service.py` (+ lesson/scenario/portfolio tutor wrappers) | `KnowledgeRepository`, `ConversationRepository`, `TutorAnswerRepository`, `GuardrailRepository`, `RetrievalAuditRepository`, `KnowledgeGapRepository` | `knowledge_documents`, `knowledge_chunks`, `knowledge_chunk_embeddings`, `tutor_conversations`, `tutor_messages`, `tutor_answers`, `tutor_answer_citations`, `tutor_guardrail_decisions`, `tutor_retrieval_runs`, `tutor_knowledge_gaps` | Yes |
| `operations.router` | `application/operations/service.py` | `BackgroundJobRepository`, `BackgroundJobAttemptRepository`, `BackgroundJobEventRepository` | `background_jobs(_attempts/_events)` | Yes |
| `quality_evaluation.router` | `application/quality_evaluation/service.py` | `QualityEvaluationSuiteRepository`, `RunRepository`, `ResultRepository`, `BaselineRepository` | `quality_evaluation_{suites,runs,sample_results,baselines}`, `quality_issues`, `quality_metric_results` | Yes |
| `integrations.router` (n8n-facing) | `infrastructure/operations/integration_auth.py` + `application/operations/service.py` | `IntegrationClientRepository`, `IntegrationRequestRepository`, `BackgroundJobRepository` | `integration_clients(_allowed_job_types)`, `integration_requests` | Yes |
| `learning_orchestrator.router` (`/coach`) | `application/learning_orchestrator/service.py` → `graph_builder.build_graph()` → **every one of the above application services**, via `AllowlistedLearningActionExecutor` | `LearningOrchestratorThreadRepository`, `RunRepository`, `EventRepository`, `ActionProposalRepository` + LangGraph's own checkpoint tables | **No — only if `LANGGRAPH_ENABLED=true`** |

**Key dependency insight:** the LangGraph coach is a *consumer* of nearly every other application service (tutor, scenarios, portfolio, adaptive learning), not a peer. Deleting or restructuring any of those underlying services without updating `application/learning_orchestrator/actions.py` (`AllowlistedLearningActionExecutor`) and `subgraphs.py` would break the coach even though the coach is currently disabled — "disabled" does not mean "safe to ignore when changing its dependencies."

---

## 3. Celery Task → Handler → Repository chains

| Celery task | Handler (`application/operations/handlers.py`) | Depends on |
|---|---|---|
| `finquest.tracked_market_refresh`, `finquest.security_market_refresh` | Market-refresh handlers | `infrastructure/market_data/yfinance_adapter.py`, `MarketBarRepository`, `TrackedSecurityRepository`, `SecurityRepository` |
| `finquest.portfolio_valuation`, `finquest.portfolio_batch_valuation` | `PortfolioValuationJobHandler`, `PortfolioBatchValuationJobHandler` | `application/virtual_portfolio/valuation_service.py`, `infrastructure/virtual_portfolio/pandas_portfolio_analytics.py` |
| `finquest.curriculum_knowledge_refresh`, `finquest.local_document_ingestion`, `finquest.knowledge_reembed` | Knowledge-ingestion handlers | `application/ai_tutor/knowledge_ingestion.py`, `infrastructure/ai_tutor/{sentence_transformer_embeddings,local_document_parsers}.py` |
| `finquest.retrieval_evaluation` | Retrieval-evaluation handler | `scripts/evaluate_tutor_retrieval.py` logic path, `application/ai_tutor/retrieval.py` |
| `finquest.knowledge_gap_summary` | Knowledge-gap summary handler | `KnowledgeGapRepository` |
| `finquest.ragas_quality_evaluation`, `finquest.learning_quality_aggregation`, `finquest.quality_baseline_comparison` | Quality-evaluation handlers | `application/quality_evaluation/{runner,regression}.py`, `infrastructure/quality_evaluation/ragas_adapter.py` (only if `ragas_enabled=true`) |
| `finquest.system_maintenance` | Maintenance handler | `infrastructure/operations/{redis_lock,metrics}.py` |

Every task is dispatched only through `BackgroundJobService` (`application/operations/service.py`), which is itself only constructed in `app_factory.py`'s lifespan and in the worker process entrypoint — there is no second, parallel job-dispatch path to account for.

---

## 4. Migrations → ORM → Repository dependency order

Migrations must remain applicable in strict order; each depends on all prior ones being applied first (Alembic enforces this via `down_revision`, already verified linear in `current-architecture-inventory.md` §6). The practical dependency for **any future migration work**:

```
0001_initial_schema
  └─ 0002_learning_core          (learning_paths, modules, lessons, exercises)
       └─ 0003_adaptive_learning  (diagnostics, mastery, misconceptions)
            └─ 0004_historical_market_scenarios
                 └─ 0005_virtual_portfolios
                      └─ 0006_grounded_ai_tutor        (pgvector extension + knowledge/tutor tables)
                           └─ 0007_product_api_auth     (identity/auth tables)
                                └─ 0008_kb_doc_context_uniqueness
                                     └─ 0009_operations_and_n8n   (background jobs, integration clients)
                                          └─ 0010_langgraph_learning_orchestrator
                                               └─ 0011_ragas_learning_quality  (head)
```

Any new migration must declare `down_revision = "0011_ragas_learning_quality"`. Any Stage 1+ work reorganizing `application/ai_tutor/*` into `application/knowledge/*` + `application/tutor/*` (per the target repository structure) must **not** attempt to also move or rename the ORM tables in the same change — table names are independent of Python package names, and doing both at once would conflate a pure refactor with a schema change, defeating the purpose of the "no application-behavior change in Stage 1" rule.

---

## 5. Frontend hook → API route dependency map (representative, not exhaustive)

| Frontend hook | Backend route(s) | Notes |
|---|---|---|
| `hooks/useAuth` / `lib/auth/*` | `POST /api/v1/auth/{login,register,refresh,logout}`, `GET /api/v1/auth/me` (proxied via `app/api/auth/*` Route Handlers) | Route Handlers are a required intermediary — they own the HttpOnly cookie; the browser never talks to the backend auth endpoints directly |
| `hooks/useCurriculum`, `useDashboard`, `useProgress` | `GET /api/v1/learning-paths`, `/lessons/{id}/exercises`, `/learners/me/{dashboard,mastery,progress,misconceptions}` | |
| `hooks/useAdaptive`, `useDiagnostic` | `/api/v1/adaptive/{sessions,decisions,diagnostics}/**` | |
| `hooks/usePortfolios` | `/api/v1/portfolios/**` (create, overview, trades preview/execute, transactions, holdings, journal, valuations, performance) | |
| `hooks/useScenarios` | `/api/v1/scenarios/**` | |
| `hooks/useTutor` | `POST /api/v1/tutor/conversations/{id}/messages` | Non-streaming |
| `hooks/useCoachStream`, `lib/api/coach-stream.ts` | `POST /api/v1/coach/threads/{id}/runs/stream`, `/runs/{id}/resume/stream` | **Only exists if `LANGGRAPH_ENABLED=true`** — if the frontend is deployed against a backend with the flag off, these calls 404. This is the one place a backend feature flag has a direct, breakable frontend dependency. |
| `hooks/useEvaluationRuns`/`useEvaluationSuites` | `/api/v1/admin/evaluations/**` | |
| `frontend/types/generated-api.ts` | generated from `frontend/openapi/finquest-api.json`, which is exported from the live backend via `scripts/export_openapi.py` | A silent drift source: if the backend schema changes without re-running `npm run api:export && api:generate`, `tsc --noEmit` may still pass (types just become stale, not wrong-shaped) — only `api:check` catches this, and it is not run automatically anywhere (no CI) |

**Concrete risk this map surfaces:** if a future stage flips `LANGGRAPH_ENABLED` on in one environment but not another (e.g., enabled in local dev, still off in production), the Coach UI will render but every request will 404 in the environment where it's off. `components/coach/*` and `app/(protected)/coach/*` should check for this (e.g., a capability-detection call) before Stage 6 makes this a real deployment topology, not just a local dev convenience.

---

## 6. n8n workflow → backend endpoint dependency

Every workflow in `n8n/workflows/*.json` depends on exactly one backend surface: `POST /api/v1/integrations/n8n/jobs`, `GET /api/v1/integrations/n8n/jobs/{id}`, `GET /api/v1/integrations/n8n/ready`. None of the 6 workflows have any other external dependency (confirmed by the dedicated n8n audit in `architecture-migration-plan.md` §2.25). This means:
- The integration router (`api/routers/integrations.py`) cannot be moved or renamed without updating the workflow JSON's `httpRequest` node URLs — a `MOVE_LATER` on the backend code triggers a mandatory, coordinated edit to the workflow files, not an independent change.
- Conversely, the workflow JSON files themselves have zero inbound Python references (only the contract test reads them) — they can be edited or replaced without touching backend code, as long as the endpoint contract they call stays the same.

## 7. LangGraph graph nodes → subgraph → service dependency

`application/learning_orchestrator/graph_builder.py`'s 22-node graph delegates actual work to `subgraphs.py`'s `Subgraphs` class, which wraps: `tutor_service` (→ `application/ai_tutor/service.py`), `lesson_tutor_service`, `scenario_tutor_service`, `portfolio_tutor_service`, `adaptive_learning_service`, `context_loader` (→ reads learning + portfolio state). **Any future split of `ai_tutor` into `knowledge`/`tutor` packages (per the target repo structure) must update these import paths in `graph_builder.py`, `nodes.py`, and `subgraphs.py` together** — they are the only consumers outside the tutor's own router, but they are real consumers, not test-only.

## 8. Knowledge Base ingestion dependency chain

```
scripts/seed_learning_curriculum.py  (must run first — creates lessons/exercises)
        │
        ▼
scripts/seed_finquest_knowledge_base.py  (reads curriculum, calls KnowledgeIngestionService.ingest_curriculum())
        │
        ▼
application/ai_tutor/knowledge_ingestion.py → chunking.py (HeadingAwareWordChunker)
        │
        ▼
infrastructure/ai_tutor/{sentence_transformer_embeddings.py | deterministic_fake_embeddings.py}
        │
        ▼
infrastructure/database/repositories/knowledge_repository.py → knowledge_documents / knowledge_chunks / knowledge_chunk_embeddings
```

Any future Markdown-corpus ingestion (Stage 3) adds a **parallel** entry point (`ingest_local_document()`, already implemented) into the same chunking → embedding → repository chain — it does not replace the curriculum-derived path, since both are expected to coexist (curriculum content and standalone reference documents are different sources feeding the same knowledge base).

---

## 9. What must change before each commonly-proposed deletion/move

| Proposed action | Must change first |
|---|---|
| Move `application/ai_tutor/*` → `application/knowledge/*` + `application/tutor/*` | `api/app_factory.py` imports (lines ~49-57, 76-87), `api/routers/ai_tutor.py`, `graph_builder.py`/`nodes.py`/`subgraphs.py` (LangGraph consumers), all `tests/unit/test_ai_tutor_*`/`tests/integration/test_ai_tutor_*` imports, `cli/ai_tutor.py`, `cli/knowledge_base.py` |
| Move `api/routers/integrations.py` + `integration_auth.py` under `infrastructure/live_research/n8n/` | Every `n8n/workflows/*.json` `httpRequest` node URL (if the route prefix changes — it need not, if only the *implementing module's location* moves, not the URL path), `tests/integration/test_integration_api.py`, `tests/integration/test_n8n_workflow_contracts.py`, `cli/operations_admin.py` |
| Delete `docker-compose.yml.backup` | Confirm with the user the one-line `HOSTNAME` divergence was an intentional, already-adopted change (see `deprecation-removal-plan.md` §4) — **done in Phase A1**: confirmed, and the file was removed via `git rm` |
| Enable `LANGGRAPH_ENABLED=true` in any shared environment | Verify the frontend deployed alongside it also expects `/api/v1/coach` to exist (see §5 risk above), and update `tests/unit/test_openapi_snapshot.py`'s allowlist deliberately at that time — **note (Phase A1):** the 2 failures previously attributed here were actually caused by a local, gitignored `.env` setting `LANGGRAPH_ENABLED=true` against the code's own `False` default, not a real enablement; Phase A1 fixed the test's hermeticity (constructs `LangGraphSettings(langgraph_enabled=False)` explicitly) without touching the allowlist or enabling LangGraph, so this row's action is still pending for whichever future phase performs a real enablement |
| Any embedding model/dimension change | Run `finquest.knowledge_reembed` (or CLI equivalent) against all existing `knowledge_chunk_embeddings` — old vectors are silently incompatible with a new dimension/model, per `architecture-migration-plan.md` risk table |

No deletion in this repository should be approved on the basis of "this file appears unused" alone — every item in this map was confirmed via imports, tests, Docker/Compose config, or documented composition roots, and several ("disabled" LangGraph, "not yet deployed" n8n) initially look unused but are fully wired to real dependents.
