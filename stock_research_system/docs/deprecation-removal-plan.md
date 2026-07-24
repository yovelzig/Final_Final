# FinQuest File Disposition Inventory

**Stage:** 0 — classification only. **No file listed here was moved, renamed, or deleted in this stage.** "Earliest safe deletion stage" is a recommendation for a future stage, not an action taken now.

Classifications: `KEEP_AS_IS` · `KEEP_AND_EXTEND` · `MOVE_LATER` · `REPLACE_LATER` · `DELETE_LATER` · `TEST_FIXTURE_ONLY` · `UNKNOWN`

Granularity note: 756 files are tracked in git. Rather than one row per file, this inventory groups files into coherent units (a package, a directory, a fixture family) and gives an exact path pattern, except for the small number of individually noteworthy files (backups, stubs, workflow exports) which get their own row.

---

## Owner Migration Decisions (Authoritative) — impact on this document's classifications

The product owner has made authoritative decisions (recorded in full in `architecture-migration-plan.md` and `migration-status.md`) that directly affect how the classifications below should be read:

- **All classifications in this document (`KEEP_AS_IS`, `KEEP_AND_EXTEND`, etc.) were made on technical/dependency-safety grounds only** — is it wired, tested, referenced, safe to delete without breaking something? That is a different question from whether the product still wants the feature. Owner Decision 4 states explicitly: test/reference existence does not by itself make a feature a product requirement.
- **Owner Decision 3** grants authority to remove existing application code, API routes, database tables, tests, old n8n workflows, diagrams, exports, and documentation when they are not relevant to the target architecture — broader than this document's original "Summary" conclusion that nothing was a confirmed deletion candidate. That conclusion was correct *as a technical-safety statement* (nothing here was found to be unsafe-to-keep or accidentally-dead code) and remains accurate as such — it should not be read as a product-relevance verdict, which this document was never positioned to make.
- **§3 (n8n)** is the section most affected: every item there was classified `KEEP`/`KEEP_AND_EXTEND` because it is real, tested, and wired — not because the product owner has confirmed the target Live Research architecture still needs today's specific n8n workflow shapes. Stage 1's product-relevance review (see `migration-status.md`'s revised Stage 1) must re-examine §3 explicitly against Owner Decisions 3-4 before treating any `KEEP` classification there as final.
- **Owner Decision 5**'s list of reusable infrastructure to preserve regardless of feature-level removal (auth, FastAPI, Next.js, Postgres, pgvector, TimescaleDB, Redis, Celery, Docker, Alembic, ports/adapters, the generic n8n-facing integration/auth contract) should be treated as a floor under any future removal decided by the Stage 1 review — none of it should be classified for removal no matter what the product-relevance review concludes about specific application features built on top of it.
- **No reclassification was performed in this pass.** This section only records that the existing classifications need a product-relevance re-read, not a re-read this Stage 0 pass is positioned to perform itself.

---

## 1. Backend package (`src/stock_research_core/`)

| Path pattern | Classification | Purpose today | References/imports | Tests | Docker/Compose dependency | Doc references | Why it remains | Replacement | Earliest safe deletion stage | Validation required before deletion |
|---|---|---|---|---|---|---|---|---|---|---|
| `domain/{identity,learning,adaptive_learning,market_scenarios,virtual_portfolio,operations,quality_evaluation,learning_orchestrator}/**` | `KEEP_AS_IS` | Core domain models, actively used | Imported throughout `application/`, `infrastructure/`, `api/` | 1165 unit tests exercise these | Baked into `Dockerfile` image | README §per-phase | Foundation of the whole system | n/a | n/a | n/a |
| `domain/ai_tutor/**` | `KEEP_AND_EXTEND` | Tutor/knowledge domain models, currently one package | Imported by `application/ai_tutor/*`, `infrastructure/ai_tutor/*` | `test_ai_tutor_domain_models.py` | Baked into image | README | Will be split into `domain/knowledge/` + `domain/tutor/` per §5 of the migration plan | `domain/knowledge/*`, `domain/tutor/*` (new) | 1 (split), keeping a re-export shim | Full test pass after split; no import errors anywhere in `src/`/`tests/` |
| `application/*/**`, `infrastructure/*/**` (all 11 application subpackages, all infrastructure adapters) | `KEEP_AS_IS` or `KEEP_AND_EXTEND` (ai_tutor only, see above) | Real, connected use-case services and adapters — see `architecture-migration-plan.md` §2 for per-capability classification | See dependency map | Extensive unit+integration coverage | Baked into image | README | All confirmed connected or intentionally flagged-off, not dead | n/a for most; `ai_tutor` splits per above | n/a | n/a |
| `api/**`, `cli/**`, `contracts/**` | `KEEP_AS_IS` | FastAPI routers/schemas, CLI entry points, cross-cutting ports | Composition roots (`app_factory.py`, each `cli/*.py`) | `test_api_*`, integration `test_*_api.py` per router | Baked into image | README | Actively used, no orphaned router found | n/a | n/a | n/a |
| `src/stock_research_core.egg-info/`, all `__pycache__/` dirs | `KEEP_AS_IS` (i.e., no action needed) | Build artifacts | none tracked | n/a | n/a | n/a | Already excluded by `.gitignore` (`__pycache__/`, `*.py[cod]`, `*.egg-info/`) and **not tracked in git** (verified via `git ls-files`) | n/a | n/a | none — already correctly ignored |

## 2. Migrations (`migrations/`)

| Path pattern | Classification | Purpose today | References | Tests | Docker/Compose dependency | Doc references | Why it remains | Replacement | Earliest safe deletion stage | Validation required |
|---|---|---|---|---|---|---|---|---|---|---|
| `migrations/versions/0001_initial_schema.py` … `0011_ragas_learning_quality.py` (11 files) | `KEEP_AS_IS` | Released schema history, linear chain, head = `0011_ragas_learning_quality` | `alembic.ini`, `migrations/env.py` | Implicitly exercised by every integration test (they run against a migrated DB) | `docker-compose*.yml` run `alembic upgrade head` at deploy | README §migrations | Per Stage 0 non-destructive rule: **released migrations must never be edited** | n/a — future changes are new migration files only | n/a | n/a |
| `migrations/versions/__pycache__/*.pyc` (incl. one stale `0008_knowledge_document_context_scoped_uniqueness.cpython-312.pyc` whose source file was apparently renamed to `0008_kb_doc_context_uniqueness.py`) | `KEEP_AS_IS` (not tracked, harmless) | Build cache | none | n/a | n/a | n/a | Not tracked in git (`.gitignore`); the stale `.pyc` for a renamed module is a local-only artifact, regenerated automatically, never read by Alembic (which reads `.py` files) | n/a | n/a | none |

## 3. `n8n/`

Full per-file audit (inbound/outbound references, Docker inclusion, test coverage, execution status) is in `architecture-migration-plan.md` §2.25 and was produced by a dedicated Stage 0 n8n audit. Summary disposition:

| Path | Classification | Purpose today | References | Tests | Docker/Compose | Doc refs | Why it remains | Replacement | Earliest safe deletion stage | Validation required |
|---|---|---|---|---|---|---|---|---|---|---|
| `n8n/README.md` | `KEEP_AS_IS` | Operator-facing design doc for the 6 workflows | none (docs) | n/a | not in any image | self | Accurate and current | n/a | n/a | n/a |
| `n8n/credentials.example.md` | `KEEP_AS_IS` | Documents the 2-header auth scheme, no secrets | none | n/a | not in any image | self | Accurate, no secrets present | n/a | n/a | n/a |
| `n8n/examples/trigger-job.sh`, `n8n/examples/trigger-job.ps1` | `KEEP_AS_IS` | Manual/CI exercisers of the integration API, independent of a running n8n instance | none (standalone scripts) | Functionally exercised by the same contract `test_integration_api.py` covers | not in any image | `n8n/README.md` | Useful without n8n installed | n/a | n/a | n/a |
| `n8n/workflows/tracked-market-refresh.json`, `portfolio-valuation.json`, `knowledge-refresh.json`, `retrieval-evaluation.json` | `KEEP_AND_EXTEND` | 4 structurally-identical polling-trigger workflows | Loaded only by `tests/integration/test_n8n_workflow_contracts.py` (structural validation) and, optionally, a live local n8n instance for import | Yes — `test_n8n_workflow_contracts.py` (always runs, no DB needed) | not in any image; n8n itself is not a Compose service | `n8n/README.md` | Real, tested, currently correct; may need new job-type variants once Live Research (Stage 7/8) defines new `BackgroundJobType`s | additive new workflow JSON files, not a rewrite of these | 8 (extend, not delete) | Re-run `test_n8n_workflow_contracts.py` after any edit; verify against a real n8n instance's `/rest/workflows` import if available |
| `n8n/workflows/quality-evaluation.json` | `KEEP_AND_EXTEND` | Same shape + baseline-comparison branch | same as above | same | same | same | same | same | 8 | same |
| `n8n/workflows/system-readiness-watch.json` | `KEEP_AS_IS` | Synchronous hourly readiness check, no polling loop | same test file | Yes | not in any image | `n8n/README.md` | Simple, low-risk, unaffected by Live Research changes | n/a | n/a | n/a |

**None of the 6 workflow files or 4 supporting files are deletion candidates.** This directly contradicts an assumption embedded in the original instructions ("some are expected to be obsolete") — Stage 0 evidence does not support that for anything under `n8n/`. The only n8n-adjacent code that will genuinely relocate (not delete) is the generic integration backend (`api/routers/integrations.py`, `integration_auth.py`, `orm/integration_{client,request}.py`) — proposed to move under `infrastructure/live_research/n8n/` in a later stage per the target repository structure, once it has research-specific siblings to sit next to. It is `KEEP_AND_EXTEND` today, `MOVE_LATER` (Stage 7+) once that reorganization is warranted.

## 4. Root-level backup/config files

| Path | Classification | Purpose today | References | Tests | Docker/Compose dependency | Doc references | Why it remains | Replacement | Earliest safe deletion stage | Validation required |
|---|---|---|---|---|---|---|---|---|---|---|
| `docker-compose.yml.backup` | `DELETE_LATER` | Pre-edit snapshot of `docker-compose.yml`; diff shows exactly **one line difference** (`HOSTNAME: 0.0.0.0` added to one service in the current file) — i.e., this is a very recent manual safety copy, not stale legacy config | None — not referenced by any script, Dockerfile, or CI | n/a | Not used by `docker compose` (only `docker-compose.yml`/`docker-compose.production.yml` are canonical) | none | **Is tracked in git** (`git ls-files` confirms) — a committed backup file is unusual and should be resolved deliberately, not left indefinitely | `docker-compose.yml` (current) is authoritative | 1 — but only after confirming with the user that the one-line `HOSTNAME` change is intentional and correct, since the backup is the only record of the pre-change state | Diff confirmed in Stage 0 (only `HOSTNAME: 0.0.0.0` differs); before deleting, confirm the user does not want this backup retained for another reason |
| `.env.backup` | `UNKNOWN` (not opened for content — may contain real secrets) | Local backup of `.env` | none | n/a | n/a | none | **Not tracked in git** (`.gitignore` excludes `.env.backup` explicitly) — already correctly kept out of version control | `.env` (current) | n/a — this is a local file outside git's purview entirely; Stage 0 makes no recommendation about locally-held files, only about what's tracked | If ever inspected, must be done without echoing contents into logs/docs |
| `.env`, `.env.example`, `.env.production.example` | `KEEP_AS_IS` | Active local env / documented example templates | Read by all `pydantic-settings` classes | n/a | `docker compose` reads `.env` | README | Standard, correct pattern | n/a | n/a | n/a |
| `README.md` (168 KB) | `KEEP_AS_IS` | Extensive phase-by-phase project log/reference, evidently kept current alongside code (matches this stage's independent findings closely) | Referenced from `docs/*.md` (this set) | n/a | n/a | self | Valuable historical record and onboarding doc; still accurate per Stage 0 spot-checks | n/a | n/a | n/a |

## 5. `docs/` (this Stage 0 set + prior stubs)

| Path | Classification | Purpose today | References | Tests | Docker dependency | Doc references | Why it remains | Replacement | Earliest safe deletion stage | Validation required |
|---|---|---|---|---|---|---|---|---|---|---|
| `docs/migration-status.md`, `docs/architecture-migration-plan.md`, `docs/production-deployment-runbook.md` (pre-Stage-0 stubs) | `REPLACE_LATER` → replaced in place this stage | Were near-empty placeholders before Stage 0 | none | n/a | n/a | n/a | Superseded in place by this Stage 0 work (same filenames, real content) | This Stage 0 content | done | n/a |
| `docs/current-architecture-inventory.md`, `docs/deprecation-removal-plan.md`, `docs/migration-dependency-map.md` (new in this stage) | `KEEP_AS_IS` | Stage 0 deliverables | this set cross-references itself | n/a | n/a | n/a | New baseline documentation | n/a | n/a | n/a |

## 6. `evaluation/`

| Path pattern | Classification | Purpose today | References | Tests | Docker dependency | Doc references | Why it remains | Replacement | Earliest safe deletion stage | Validation required |
|---|---|---|---|---|---|---|---|---|---|---|
| `evaluation/suites/*.jsonl`, `finquest-learning-outcomes-v1.json` | `KEEP_AND_EXTEND` | Real evaluation case sets consumed by `application/quality_evaluation/*` | `infrastructure/quality_evaluation/dataset_loader.py`, `scripts/seed_quality_evaluation_fixtures.py` | `test_evaluation_dataset_loader.py` | none | `evaluation/README.md` | Active input data for a real, connected feature | n/a — will gain siblings for live-research/knowledge-corpus evaluation | n/a | n/a |
| `evaluation/generated/.gitkeep` | `KEEP_AS_IS` | Placeholder to keep an otherwise-empty output directory in git | `.gitignore` presumably ignores generated content itself | n/a | n/a | n/a | Standard pattern | n/a | n/a | n/a |

## 7. `scripts/`

| Path pattern | Classification | Purpose today | References | Tests | Docker dependency | Doc references | Why it remains | Replacement | Earliest safe deletion stage | Validation required |
|---|---|---|---|---|---|---|---|---|---|---|
| `scripts/seed_learning_curriculum.py`, `seed_historical_market_scenarios.py`, `seed_adaptive_learning_profiles.py`, `seed_finquest_knowledge_base.py`, `seed_quality_evaluation_fixtures.py` | `KEEP_AS_IS` | Idempotent, uuid5-keyed content seeders — real, current | Documented in README, invoked manually per phase | Not directly unit-tested (seed scripts), but their output is exercised by integration tests that read the seeded tables | Not baked into any image; run manually/CI only | README | Only source of curriculum/scenario/KB content today | n/a | n/a | n/a |
| `scripts/seed_e2e_synthetic_market_data.py` | `TEST_FIXTURE_ONLY` | Synthetic OHLCV for 2 fixture tickers, Playwright-only | `frontend/e2e/*` rely on this data existing | Used by Playwright e2e setup | none | README | Correctly scoped to test/demo, never called from production code | n/a | n/a | n/a |
| `scripts/wait_for_database.py`, `export_openapi.py`, `init_test_db.sql`, `evaluate_tutor_retrieval.py` | `KEEP_AS_IS` | Operational tooling (DB readiness poll, OpenAPI export for frontend codegen, test-DB init, retrieval evaluation) | `frontend/package.json` `api:export` calls `export_openapi.py`; `docker-compose.yml` mounts `init_test_db.sql` | n/a | `init_test_db.sql` mounted into `stock-db` init | README | Active, small, single-purpose | n/a | n/a | n/a |

## 8. `tests/`

| Path pattern | Classification | Purpose today | References | Tests-of-tests | Docker dependency | Doc references | Why it remains | Replacement | Earliest safe deletion stage | Validation required |
|---|---|---|---|---|---|---|---|---|---|---|
| `tests/unit/**` (85 files, 1165 tests, 2 known pre-existing failures) | `KEEP_AND_EXTEND` | Backend unit test suite | `pyproject.toml` pytest config | n/a | n/a | this doc, `current-architecture-inventory.md` §12 | Comprehensive, high-value | n/a — grows with each stage | n/a | n/a |
| `tests/unit/test_openapi_snapshot.py` | `KEEP_AND_EXTEND` (fix deferred, not deleted) | OpenAPI contract snapshot | reads live app's generated spec | n/a | n/a | this doc | Currently has 2 failing assertions due to LangGraph coach paths not yet added to its allowlist — a real, acknowledged drift, not obsolete | Update the allowlist deliberately when the coach API is intentionally finalized | 6 (or whenever coach surface is next intentionally changed) | Decide the final `/api/v1/coach/*` surface first, then update in the same change |
| `tests/integration/**` (64 files) | `KEEP_AND_EXTEND` | Backend integration suite against real `stock_research_test` DB | `@pytest.mark.integration` | n/a | requires local `stock-db` | this doc | Comprehensive; skip cleanly if DB unreachable | n/a | n/a | n/a |
| `tests/test_market_data_service.py`, `test_models.py`, `test_yfinance_adapter.py`, `test_yfinance_resolver.py` (loose, top-level) | `UNKNOWN` (mild inconsistency, not a defect) | Same role as `tests/unit/*` but not placed in the `unit/` subdirectory | pytest discovers them via `testpaths = ["tests"]` | n/a | n/a | none | Functionally fine (pytest finds them regardless of subdirectory), but inconsistent with the unit/integration split documented in the README | Could be moved into `tests/unit/` for consistency | 1 (cosmetic only, zero risk) | Confirm they still collect and pass after any move; update README if the convention changes |

## 9. `frontend/`

| Path pattern | Classification | Purpose today | References | Tests | Docker dependency | Doc references | Why it remains | Replacement | Earliest safe deletion stage | Validation required |
|---|---|---|---|---|---|---|---|---|---|---|
| `frontend/app/**`, `frontend/components/**`, `frontend/hooks/**`, `frontend/lib/**`, `frontend/providers/**` | `KEEP_AS_IS` or `KEEP_AND_EXTEND` (i18n-affected areas only, Stage 9) | Full Next.js app — routes, auth, learning, tutor/coach, portfolio, scenarios, admin/evaluations, all confirmed connected | `package.json` build/dev/test scripts | 34 test files, 154 tests, all passing | `Dockerfile`/`docker-compose*.yml` build `finquest-web` | this doc, `current-architecture-inventory.md` §11 | Fully live, current | n/a | n/a | n/a |
| `frontend/openapi/finquest-api.json`, `frontend/types/generated-api.ts` | `KEEP_AS_IS` (generated) | Backend-schema-derived TypeScript types | `api:generate`/`api:check` scripts | Implicitly (typecheck would fail if stale and used) | none | `package.json` | Codegen artifact, must stay in sync manually via the `api:*` scripts | n/a | n/a | Re-run `npm run api:export && npm run api:generate && npm run api:check` after any backend schema change |
| `frontend/tests/**`, `frontend/e2e/**` | `KEEP_AND_EXTEND` | Full test pyramid (unit/component/integration/a11y/e2e) | `package.json` test scripts | self | none | this doc | Comprehensive, layered, all passing | n/a | n/a | n/a |
| `frontend/node_modules/`, `frontend/.next/`, `frontend/playwright-report/`, `frontend/test-results/` | `KEEP_AS_IS` (no action — build artifacts) | npm deps / Next.js build cache / Playwright report output | n/a | n/a | n/a | n/a | Not tracked in git (standard `.gitignore` pattern for a Next.js app — verified none appear in `git ls-files`) | n/a | n/a | none |

---

## Summary

**No files in this repository were identified in Stage 0 as *technically unsafe* to delete.** The only concrete deletion candidate on technical-safety grounds alone is `docker-compose.yml.backup` (pending user confirmation that its one-line divergent config was superseded intentionally). Everything under `n8n/` — the area the task instructions anticipated might contain obsolete material — was independently verified to be current, tested, and either `KEEP_AS_IS` or `KEEP_AND_EXTEND` *on technical grounds*. The one cosmetic inconsistency found (4 loose test files not under `tests/unit/`) is zero-risk.

**This conclusion is technical-safety-only and has since been superseded in scope, not overturned in substance, by the Owner Migration Decisions recorded above and in `migration-status.md`.** Technical safety was never the same question as product relevance, and the owner has now granted explicit authority (Decisions 3-4) to remove technically-safe-to-keep items that are nonetheless not relevant to the target architecture — including, potentially, `n8n/` items classified `KEEP` above. Which specific items that applies to is Stage 1's product-relevance review to determine, not a conclusion this Stage 0 pass draws.
