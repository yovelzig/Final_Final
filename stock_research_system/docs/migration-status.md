# FinQuest Migration Status

**Current Production Commit:** not tracked in this file as a live pointer — this file tracks the *migration branch's* status, not production. The authoritative record of what's deployed lives in the operator-owned deployment log described in `production-deployment-runbook.md` §3 (EC2 flow, step 11), e.g. `/home/ubuntu/deployments/finquest-deployments.log` — never written by editing this file directly on the EC2 checkout. If this file's own historical record of deployments needs updating, that happens locally, via the normal commit → push → PR → merge flow, like any other change (Claude Code has no EC2 access and cannot read the commit actually deployed there).
**Local baseline commit (this Stage 0 work):** `c1f9e2240594cb237a1d13abab042fcece7bf04f` on branch `migration/stage-00-baseline`.
**Phase A1 baseline commit:** `5f1d2d36a51296f0a501559c1951185b006026cb` on branch `migration/phase-a1-baseline-stabilization`.
**Phase A2 baseline commit:** `a796caa33b873f9a302bf9f8c874175c71991e29` on branch `migration/phase-a2-production-images-worker-health`.

---

## Master-Spec Phase Plan (Authoritative — supersedes Stage numbering below)

> Effective 2026-07-24. This section is the current source of truth for phase sequencing. The Owner Migration Decisions immediately below remain fully authoritative and are shared by both this Phase Plan and the historical Stage-based plan further down this document. The Stage 0–10 plan later in this document is **preserved, not deleted** — see the "Historical: Stage-based plan (superseded)" callout right before it.

### Phase Plan

| Phase | Name | Status |
|---|---|---|
| A1 | Baseline stabilization and master-spec alignment | Complete |
| A2 | Production image and worker-health correction | Complete (deployed to EC2 by the human operator) |
| B | Curriculum and first usable learner flow | Local implementation and Phase B-specific verification complete. B1 and B2 are complete and reviewed. B3 implementation and verification are complete locally. The combined Phase B diff is awaiting final external review. Phase B has not been committed, pushed, merged, or deployed. |
| C1 | Knowledge document framework | Not started |
| C2.1 | Seed knowledge documents 01–05 | Not started |
| C2.2 | Seed knowledge documents 06–10 | Not started |
| C2.3 | Seed knowledge documents 11–15 | Not started |
| F1 | S3 infrastructure and adapter | Not started |
| C3 | Knowledge ingestion and retrieval | Not started |
| D | Ollama Cloud Tutor | Not started |
| E | Guardrails and Knowledge Sufficiency Gate | Not started |
| G1 | Live Research domain | Not started |
| G2 | n8n Cloud, Perplexity, SEC, and company IR/market data | Not started |
| H | OpenAI evidence synthesis | Not started |
| I | LangGraph production orchestration (enablement) | Not started |
| J | Product completion, database cutover, and operations | Not started |

### Explicit platform/provider clarifications (binding on every later phase)

- **Ollama Cloud**, not a locally-hosted Ollama instance or a second Ollama EC2 instance.
- **n8n Cloud** (`https://yovel.app.n8n.cloud/`), not self-hosted n8n — no n8n Docker service, DNS, or Caddy routing.
- **S3** (or an S3-compatible bucket), not MinIO — production S3 access will later use an EC2 IAM role/Instance Profile, not long-lived access keys in production `.env`.
- **English frontend and curriculum in the first release**; Tutor input/output must later support English and Hebrew, with correct RTL rendering for Hebrew.
- **Ollama Cloud** is the educational grounded Tutor provider; **OpenAI** is a separate, optional provider for normalized live-research evidence synthesis, architecturally distinct from the Tutor.
- **Perplexity** is a discovery/research provider, not the source of truth for official numerical financial data.
- **Existing SentenceTransformer embeddings remain unchanged** through at least Phase A1/A2 — no embedding-model change in this phase.
- Phase A1 deletes and rewrites **no** n8n workflow artifact — existing artifacts are replaced only once the future `finquest_live_research` workflow exists and passes contract tests (Phase G2).
- Phase A1 performs **no** production database reset (Owner Decision 6 below still gates this).

### Active Phase

**Phase A2 is complete and was deployed to EC2 by the human operator.** The current phase is **B — Curriculum and first usable learner flow**.

Phase B local implementation and Phase B-specific verification are complete.

B1 and B2 are complete and reviewed.

B3 implementation and verification are complete locally.

The combined Phase B diff is awaiting final external review.

Phase B has not been committed, pushed, merged, or deployed.

(See "Phase B — Detail" below for the full verification history, including three frontend defects found and fixed during real-stack E2E and the full integration-suite Redis-availability finding.)

### Phase A1 — Detail

- **Goal:** Establish a clean, trustworthy baseline — aligned with this new Master Spec — before any production image, curriculum, knowledge-base, provider, research, or schema work begins.
- **Allowed changes:** Fix `tests/unit/test_openapi_snapshot.py`'s two failing assertions (test hermeticity, not a contract change); add `.github/workflows/ci.yml`; delete the confirmed-obsolete `docker-compose.yml.backup`; validate both Compose files; update this documentation set to record the new phase sequence, with the historical Stage 0–10 plan preserved.
- **Prohibited changes:** Any domain/application/infrastructure code change beyond the one test-file fix; any API route, schema, or Dockerfile change; any production Compose *behavior* change; any `.env`/`.env.production.example` change; any migration; any n8n artifact deletion/rewrite; any Ollama/OpenAI/Perplexity/S3/LangGraph activation; any database reset; any commit, push, or production deployment performed by Claude Code.
- **Expected migrations:** None.
- **Expected affected services:** None at runtime — CI/test-fixture/documentation only.
- **Local test requirements:** `pytest tests/unit -q` clean; frontend `typecheck`/`lint`/`test` clean; both Compose files validate via `config --quiet`.
- **Production deployment impact:** None — no EC2 access used or required; the user reviews, commits, pushes, merges, and deploys manually.
- **Rollback checkpoint:** A Git revert of this phase's PR — nothing is committed by Claude Code in this phase.
- **Definition of done:** `test_openapi_snapshot.py` has zero failures; `.github/workflows/ci.yml` exists and is scoped as described; `docker-compose.yml.backup` is removed; both Compose files validate; this document records the new Phase Plan while preserving Stage 0–10 as history.

### Phase A1 correction note — OpenAPI snapshot root cause

The two `test_openapi_snapshot.py` failures recorded during Stage 0 (see `current-architecture-inventory.md` §12.1 and the corresponding row in `migration-dependency-map.md`) were re-investigated in Phase A1 and found to have a narrower cause than originally recorded: a local, gitignored `stock_research_system/.env` had `LANGGRAPH_ENABLED=true` set, which registered the Coach router in that specific environment only — the code's own default is `langgraph_enabled=False`, and a CI runner or fresh clone without that local `.env` would never reproduce the failures. Phase A1 fixed this by making the test construct `LangGraphSettings(langgraph_enabled=False)` explicitly (hermetic, deterministic), without touching the snapshot's path/tag allowlist and without enabling LangGraph — that remains Phase I's scope. See `current-architecture-inventory.md`'s Phase A1 addendum for the full technical detail.

### Phase A2 — Production Image and Worker-Health Correction — Detail

- **Goal:** Correct `docker-compose.production.yml`'s build targets (all five backend services had been built on the `ai` stage, bundling `sentence-transformers`/torch into workers whose job handlers never use it); make the worker healthcheck target-aware via a `--require-embedding` flag; close a production-safety gap in the Knowledge Base seed script; get operational scripts into both Docker image stages; keep the `ai` image CPU-only and reasonably sized; and define a repeatable, secret-safe Postgres backup procedure ahead of future data-transformation phases.
- **Dependency-audit conclusion (verified, not assumed):** traced every `BackgroundJobType` in `job_registry.py`'s `_JOB_TYPE_CONFIG` against its handler. `finquest.market`, `finquest.portfolio`, and `finquest.default` (`SYSTEM_MAINTENANCE`, the only occupant) carry no job whose handler calls an embedding provider. `SentenceTransformerEmbeddingAdapter` only imports `sentence_transformers` lazily inside `_load_model()` (called from `embed_texts()`), never at construction or module-import time, so `celery_tasks.py`'s unconditional per-worker adapter construction is safe on `base`. Confirmed empirically: `celery_tasks` imports cleanly, `worker_status --help` runs, and `sentence_transformers` is absent, inside the built `finquest-a2-base:local` image.
- **`ai`-image CPU/size correction:** the first `ai` build (before this correction) resolved an unpinned torch from PyPI's default index, which pulled the CUDA/NVIDIA-bundled wheel (`torch==2.13.0+cu130`, 13 `nvidia-*` packages, `cuda-toolkit`, `triton`) — 9.39GB total, ~4.6GB of it CUDA/NVIDIA packages the CPU-only production EC2 host can never use. Fixed by pinning `torch==2.13.0+cpu` from `https://download.pytorch.org/whl/cpu`, installed in its own `RUN` step immediately before `.[ai_tutor]`, so pip's resolver treats torch as already satisfied and never reaches for the CUDA build. Rebuilt image: **2.85GB** (a 70% reduction), confirmed `torch.version.cuda is None` and zero `nvidia-*`/`cuda-*`/`triton` packages installed. A new contract test (`TestAiStageUsesPinnedCpuTorch` in `test_docker_image_contract.py`) locks this in.
- **Backup-script hardening (three correction rounds):** (1) signal handling — `trap cleanup EXIT` plus separate `trap 'exit 130' INT`/`trap 'exit 143' TERM` (a combined `trap ... EXIT INT TERM` doesn't actually terminate on a signal); `--source-commit SHA_OR_REF` (default `HEAD`, validated via `git rev-parse --verify`) so the first A2 deployment can label a backup with the still-running pre-deploy commit instead of the just-pulled `HEAD`; `--backup-dir` safety enforced (not just documented) via `git rev-parse --show-toplevel` + `realpath -m`, rejecting a directory equal to or nested under the checkout; missing/empty `--backup-dir`/`--source-commit` values exit `2` instead of a raw `set -u` error. (2) Validation reordering — all Git-only checks (source-commit, checkout/backup-dir paths) now run *before* the `.env`/Compose-file checks, which run before any Docker access, so the Git-only paths are provably independent of whether `.env` exists (exercised in CI/tests via a throwaway temp Git repo with no `.env`). (3) No-overwrite protection — an existing final backup filename is rejected before the rename, the rename itself uses `mv -n` (no-clobber), and the temp file's continued existence afterward is checked and treated as a hard failure, so a same-named backup can never be silently overwritten. Two incidental bugs surfaced and fixed during this work: an unquoted heredoc whose backtick-styled prose (`` `git pull` ``) was actually executed as a live command every time `--help` ran, and a path-normalization mismatch between `git rev-parse --show-toplevel` (can emit a drive-letter path) and `realpath`/`pwd` (POSIX-style) that silently defeated the directory-safety check on non-Linux dev hosts.
- **Allowed changes (all applied):** `Dockerfile` (`COPY scripts ./scripts` in the shared base stage; stale-comment correction; pinned CPU-only `torch==2.13.0+cpu` install before `.[ai_tutor]` in the `ai` stage); `docker-compose.production.yml` (targets: `finquest-worker-market`/`-portfolio`/`-default` `ai`→`base`, `finquest-api`/`-worker-knowledge` unchanged at `ai`; only the knowledge worker's healthcheck gained `--require-embedding`; no service/queue/container/env-var/port/network/volume names changed); `src/stock_research_core/cli/worker_status.py` (`--require-embedding` flag, `main_async(*, require_embedding: bool = False)`); `scripts/seed_finquest_knowledge_base.py` (`_validate_seed_embedding_safety()` production-safety gate, called inside `_run()`'s existing `try` block before any engine is created — reuses `OperationsSettings`, `FinquestEnv`, and the existing `UnsafeEmbeddingProviderConfigurationError`/`ALLOW_FAKE_EMBEDDINGS_IN_PRODUCTION` contract, no new environment variable); `scripts/backup_production_database.sh` (new EC2-host operator script — copied into both images as part of `scripts/`, but must be invoked only on the EC2 host itself, never from inside a container); four new/extended unit test files; `docs/production-deployment-runbook.md` and this file.
- **Prohibited changes (respected):** no service/queue/package rename; no new port binding (`127.0.0.1:${API_HOST_PORT:-8080}:8080` and `127.0.0.1:${WEB_HOST_PORT:-3000}:3000` verified unchanged via `docker compose config`); no Alembic migration; no product/API/domain behavior change; no frontend or n8n file touched; no `.env` read, written, or printed; no commit, push, merge, or EC2 action performed.
- **Expected migrations:** None.
- **Expected affected services (on future EC2 deploy, not yet performed):** `finquest-api`, `finquest-worker-knowledge`, `finquest-worker-market`, `finquest-worker-portfolio`, `finquest-worker-default`. `finquest-web`, `stock-db`, and `redis` are untouched.
- **Local test requirements — all met:** targeted new tests (worker-status behavior, seed-script safety gate, task-routing drift guard, Docker/Compose contract incl. the CPU-torch pin, backup-script signal handling/`--source-commit`/directory-safety/pre-Docker validation ordering/no-overwrite protection) all pass (**73**); full `pytest tests/unit -q` → **1222 passed**; `git diff --check` clean; `docker compose --env-file <placeholder> -f docker-compose.production.yml config --quiet` → exit 0; both `base` and `ai` images built and re-verified sequentially across four correction rounds (image targets/healthchecks, CPU-torch pin, backup-script signal/commit/directory hardening, pre-Docker validation reordering + no-overwrite) and passed every requested smoke test each time, including `test -x` on the backup script; `bash -n scripts/backup_production_database.sh` → clean.
- **Production deployment impact:** None yet — no EC2 access used; see `production-deployment-runbook.md` §7 for the exact future deployment steps, written for a human operator to run manually, including the first-deployment-specific backup-script ordering (the script is new in this phase and doesn't exist on the pre-A2 commit being pulled from).
- **Rollback checkpoint:** A Git revert of this phase's PR, followed by rebuilding the five affected services on their prior targets (`production-deployment-runbook.md` §7).
- **Remaining limitations:** the backup script has been created and syntax-validated locally but **not executed or verified against the real production database** — that remains a required human action on EC2 before it can be relied on for a real migration/data-transformation phase. Local Docker images built during this work are tagged `finquest-a2-base:local`/`finquest-a2-ai:local` for inspection, not pushed to any registry.
- **Definition of done:** met — see the test/build/validation results above; this document and `production-deployment-runbook.md` record the new contract.
- **Phase B entry criteria:** satisfied — the human operator deployed Phase A2 to EC2 following `production-deployment-runbook.md` §7 and confirmed worker health in production before Phase B (curriculum work) began.

---

### Phase B — Curriculum and First Usable Learner Flow — Detail

- **Goal:** Seed and expose a first real, usable curriculum ("Investing Foundations": 8 skills, 1 path, 4 modules, 8 lessons, 24 exercises, 24 adaptive profiles) through the API and frontend, with lesson completion and a "Continue learning" flow.
- **Allowed changes:** curriculum/adaptive-profile domain, application-service, API, and repository work (B1/B2); curriculum/lesson frontend pages and components (B1/B2); two new deterministic seed-test files (`tests/integration/test_seed_learning_curriculum.py`, `tests/integration/test_seed_adaptive_learning_profiles.py`, added in B3); a one-constant scoping correction to `scripts/seed_adaptive_learning_profiles.py` (B3, see below); this documentation set.
- **Expected migrations:** None. Confirmed — the full local verification pass in B3 included the full `pytest tests/integration` suite (Alembic head unchanged at `0011_ragas_learning_quality`) and a `git diff` scope check; no new migration file exists anywhere in the B1/B2/B3 diff.
- **Expected affected services:** `finquest-api`, `finquest-web` only. Confirmed via `git diff` scope review — no worker, Compose, or environment-variable file changed.
- **Seed procedure:** curriculum seed must run before the adaptive-profile seed. Local: `python scripts/seed_learning_curriculum.py` then `python scripts/seed_adaptive_learning_profiles.py`. Production (once deployed): `dc exec finquest-api python scripts/seed_learning_curriculum.py` then `dc exec finquest-api python scripts/seed_adaptive_learning_profiles.py`. Both scripts are idempotent, deterministic-UUID-keyed, update-in-place on rerun, and are explicit operator-run commands — never invoked automatically by any Dockerfile `CMD`/`ENTRYPOINT` or app-startup path.
- **B3 scoping correction to the adaptive-profile seed:** `scripts/seed_adaptive_learning_profiles.py` previously traversed *every* `LearningPath` in the database when building adaptive profiles, not only the seeded "Investing Foundations" subtree — a genuine production-correctness gap if any unrelated curriculum content exists. B3 added a `_TARGET_PATH_CODE = "investing-foundations"` filter immediately after the path lookup, so the script now only ever creates/updates profiles for the seeded subtree. This is proven by a dedicated new test, `test_adaptive_seed_ignores_unrelated_curriculum`. Production verification should query the deterministic seed IDs/codes directly (as the new tests do), not assert that shared tables (e.g. `financial_skills`, `learning_paths`) contain only the seeded rows.
- **B3 local verification results:**
  - New seed tests: 10/10 passed, zero skips (`test_seed_learning_curriculum.py`, `test_seed_adaptive_learning_profiles.py`).
  - Backend unit suite: 1250 passed.
  - The final focused inactive-exercise correction run passed 78 tests.
  - Other B1/B2 focused integration files (`test_curriculum_repository.py`, `test_attempt_repository.py`, `test_curriculum_api.py`, `test_learning_service.py`): 90 passed.
  - Full `pytest tests/integration` (host Redis unreachable, the repo's default local setup): 395 passed, 217 skipped, **11 failed** — all 11 were `test_orchestrator_api.py`/`test_orchestrator_concurrency.py`/`test_orchestrator_end_to_end.py`/`test_orchestrator_resume.py`, every one failing identically with `redis.exceptions.ConnectionError: ... connecting to localhost:6379`, because `docker-compose.yml`'s `redis` service deliberately has no host port mapping (container-network-only) and the LangGraph learning-orchestrator's Redis-backed distributed run-lock cannot be reached from a host-run pytest process.
  - **This was independently confirmed, not just inferred:** the same full suite was re-run with a temporary, loopback-only `redis:7-alpine` container bound to `127.0.0.1:6379` (started only for this verification, stopped and removed immediately afterward — `docker-compose.yml` itself was never changed). With Redis reachable, the result was **623 passed, 1 skipped (`test_n8n_workflow_contracts.py` — no local n8n instance, an unrelated, pre-existing gap), 0 failed.** This proves conclusively that the 11 failures are caused solely by host-Redis unavailability, not by any Phase B code — confirmed additionally by inspection that no file in the B1/B2/B3 diff touches `application/learning_orchestrator/`, `infrastructure/operations/redis_lock.py`, or any orchestrator router. Recorded here as a known local-verification-environment limitation: running the full integration suite outside the Compose network requires either a temporary host-exposed Redis (as above) or accepting the 11 orchestrator-test failures as expected in that mode.
  - Frontend: `typecheck`, `lint`, and `api:check` all clean throughout (the `api:export` → `api:generate` → `api:check` regeneration chain, run once during initial B3 verification, caught and corrected one genuine pre-existing staleness — the working tree's `openapi/finquest-api.json`/`types/generated-api.ts` were missing `SubmitAnswerResponse.explanation: string | null` even though the backend schema already defined it; no backend schema changed after that, so later passes only ran `api:check`). Full Vitest suite, final state: 37 files / 176 tests passed (up from the original 173 — 3 new regression tests added for the percentage and radio-group-name defects, plus 2 updated Case B assertions for the native-anchor CTA). `next build`: succeeded.
  - Production Compose validation: `docker compose -f docker-compose.production.yml config --quiet` passed; `--services` returned exactly the 8 expected services; no change to `docker-compose.production.yml` or `.env.production.example`.
  - **Real-stack E2E, first pass — two confirmed defects, now fixed:** `e2e/registration-curriculum.spec.ts` passed. `e2e/lesson-completion.spec.ts` (new in B2, run for the first time in B3) **failed** on its second exercise (`locator.check: Clicking the checkbox did not change its state`), with independent corroborating evidence of a second defect in the same run: the page showed `"Lesson progress: 3333% complete."` Both were root-caused by reading the code and both are now fixed:
    1. **Percentage double-scaling** — `application/learning/models.py`'s `Progress.completion_percentage` is already expressed on a 0–100 scale (`Field(..., ge=0, le=100)`, computed as `100.0 * passed / total`), but `frontend/components/exercises/ExerciseResult.tsx` computed `Math.round(completion_percentage * 100)`, multiplying an already-percentage value by 100 again (33.33 → 3333). Fixed by removing the extra `* 100`. Covered by two new tests in `tests/component/exercise-player.test.tsx`: `renders a partial completion_percentage (already 0-100) without double-scaling it` and `renders a completed completion_percentage of 100 without double-scaling it`.
    2. **Shared radio-group name** — `frontend/components/exercises/SingleSelectInput.tsx` hardcoded `name="single-select-answer"` on every radio input; since a lesson page mounts one `SingleSelectInput` per SINGLE_CHOICE/TRUE_FALSE exercise, every exercise's radios belonged to one browser-level group, so selecting an option in one exercise could clear another exercise's selection. Fixed using `useId()` to give each mounted instance a distinct, stable group name. Covered by a new test: `keeps two mounted exercises' selections independent and gives their radio groups different names`.
  - **Real-stack E2E, second pass — a third, distinct defect, now fixed:** after both fixes above, `registration-curriculum.spec.ts` still passed, and `lesson-completion.spec.ts` completed all three exercises correctly (no radio-click error, no percentage-display error — progress renders `33%`/`67%`/`100%` as expected) and reached the lesson-completion banner and a correctly-populated "Continue learning" CTA (`href="/lessons/bbd60cce-a732-5b48-be49-60f41f07ba4d"`, confirmed different from the source lesson's path before clicking). The spec's original assertion (`page.waitForURL("**/lessons/*")` then `expect(page.url()).not.toBe(lessonUrl)`) was itself weak, since that glob matches both the source and destination lesson URL — it was replaced with an exact-destination assertion (`await expect(page).toHaveURL(destinationUrl.toString())`, a real 5-second retrying wait, no glob). **With that corrected, precise assertion, the test failed deterministically, proving a genuine product defect:** clicking "Continue learning" produced no navigation at all — both `page.url()` and the rendered `<h1>` stayed on the source lesson for the full 5-second retry window. A direct-navigation diagnostic (`page.goto()` straight to the destination URL) proved the destination route itself was valid (correct heading rendered immediately) — the defect was isolated to the CTA's client-side transition specifically. Observed failure mechanism: the specific Continue learning CTA in `frontend/app/(protected)/lessons/[lessonId]/LessonPageContent.tsx` rendered the correct destination href, but its client-side `Link` transition repeatedly did not change the URL or rendered lesson. Direct navigation proved the destination route was valid. Replacing this one CTA with a native anchor restored reliable navigation. The deeper Next.js/App Router-level cause was not determined. **Fixed** by replacing only that one CTA with a native `<a>` element (an intentional full document navigation for this one recovery-critical CTA) — the other two "Review learning paths" `Link` usages (pointing to the different `/learn` route, never observed to fail) were left unchanged. Covered by new assertions in `tests/component/lesson-page.test.tsx`'s two Case B tests confirming the rendered element's `tagName` is `"A"`. Final deterministic real-stack E2E verification used `--repeat-each=2`: **4 passed, 0 failed** — `registration-curriculum.spec.ts` and `lesson-completion.spec.ts` (full journey, including the exact destination URL and the "What Inflation Does to Purchasing Power" heading) both pass, each run twice.
- **Production deployment impact:** None yet — Phase B has not been committed, pushed, merged, or deployed.
- **Rollback checkpoint:** A Git revert of Phase B's PR; no migration downgrade needed (none ran). Seeded curriculum data may remain after a code-only rollback, since old code can still read the unchanged schema; a database backup is needed only if a real data rollback is required.
- **Definition of done:** met locally. All three frontend defects found during real-stack E2E are fixed and regression-tested (component tests plus a passing full E2E re-run); the E2E spec's destination-navigation assertion is now precise (a genuine retrying `toHaveURL` check, not a same-glob false pass); the full backend integration suite is confirmed clean with Redis reachable; production Compose validation passed. Phase B local implementation and Phase B-specific verification are complete. B1 and B2 are complete and reviewed. B3 implementation and verification are complete locally. The combined Phase B diff is awaiting final external review. Phase B has not been committed, pushed, merged, or deployed.

---

## Owner Migration Decisions (Authoritative)

Recorded directly from the product owner during Stage 0. These are **authoritative** and supersede any conflicting Stage 0 conclusion drawn purely from technical/dependency analysis — see `architecture-migration-plan.md`'s fuller "Owner Migration Decisions" section for the complete rationale. Summary:

1. Existing PostgreSQL production data is **not business-critical** and may be reset during a planned migration — but see decision 6 (not yet).
2. **Mandatory preservation boundary** (the only hard constraints): current AWS EC2, current Elastic IP and DNS, `researchstock.store`, `api.researchstock.store`, Caddy, HTTPS, public Web through Caddy to `localhost:3000`, public API through Caddy to `localhost:8080`, GitHub-based deployment. Everything else is in scope for change.
3. Existing application code, API routes, database tables, tests, old n8n workflows, diagrams, exports, and documentation **may be removed or replaced** when not relevant to the target architecture — broader authority than Stage 0's original conservative "nothing is a confirmed deletion candidate" conclusion.
4. Test or reference existence does **not** by itself make a feature a product requirement. Tests for intentionally removed features should be removed or replaced with the feature, not preserved as an orphaned constraint.
5. **Preserve reusable infrastructure where useful**: authentication, FastAPI, Next.js, PostgreSQL, pgvector, TimescaleDB, Redis, Celery, Docker, Alembic, ports/adapters architecture, and generic secure integration contracts.
6. **Do not reset the production database yet.** A reset is permitted only after new schema, migrations, bootstrap/seed, admin-account recreation, and smoke tests are all validated locally first.
7. **Stage 1 is revised** into a Controlled Structural Reset — see the revised Stage 1 section below.

**This pass is documentation-only.** No file was deleted, moved, or modified as application code as a result of recording these decisions. Deciding exactly *which* specific items are "confirmed obsolete" under decisions 3-4 is Stage 1's own first work item, not resolved here.

---

## Historical: Stage-based plan (superseded)

> Everything from this heading through "## Stage 1 Entry Criteria" below is Stage 0's own Stage 0–10 plan, preserved verbatim as a historical record. It is **superseded by the Master-Spec Phase Plan above as of Phase A1** and should not be extended going forward — use the Phase Plan above for current sequencing. Nothing in this section has been edited or moved as part of Phase A1.

## Stage Plan

| Stage | Name | Status |
|---|---|---|
| 0 | Baseline, inventory, dependency map, and safety documentation | **ACTIVE** |
| 1 | Controlled Structural Reset (repository cleanup, CI foundation, product-relevance-based removal) | Not started |
| 2 | Production Docker image and worker-health correction | Not started |
| 3 | Markdown Knowledge Base foundation | Not started |
| 4 | Ollama grounded Tutor | Not started |
| 5 | Guardrails and Knowledge Sufficiency Gate | Not started |
| 6 | Top-level LangGraph orchestration (enablement) | Not started |
| 7 | Live Research domain | Not started |
| 8 | n8n, Perplexity, SEC, and structured market data | Not started |
| 9 | Learning Engine expansion | Not started |
| 10 | Final production migration and hardening | Not started |

## Active Stage

**Stage 0 — Baseline, inventory, dependency map, and safety documentation.**

## Known Production Limitations (carried forward from pre-Stage-0 notes, now verified against code)

- ~~Static curriculum is not populated~~ — **superseded finding:** a real curriculum ("Investing Foundations": 1 path, 4 modules, 8 lessons, 24 exercises) *is* seeded via `scripts/seed_learning_curriculum.py`; it is modest in size, not absent. Whether it has actually been run against the production database is unverified from the repository alone (Claude Code has no EC2/production DB access) — treat "is the production DB seeded" as an open question for the deploying human, not a code gap.
- Knowledge Base content today is derived exclusively from curriculum lessons/exercises, not from a curated Markdown corpus — confirmed accurate; Stage 3 addresses this.
- Tutor generation defaults to a non-LLM extractive strategy (`DeterministicExtractiveTutor`), not "always abstains" literally — it always answers using retrieved evidence via keyword-overlap extraction, never fabricates, and falls back to an explicit insufficient-evidence message only when no relevant chunks are retrieved. A **generic** OpenAI-compatible adapter exists and is reusable against Ollama's endpoint (`REUSABLE_GENERIC_ADAPTER_EXISTS / OLLAMA_NOT_INTEGRATED` — see `architecture-migration-plan.md` §2.15) — Ollama itself is not integrated: no model is configured, no Ollama service is deployed, and no Ollama-specific test exists. Stage 4 addresses building the actual integration and, only then, making it the default in target environments.
- LangGraph orchestrator is fully implemented (real `langgraph` `StateGraph`, real Postgres checkpointer, SSE, 22-node graph, human-in-the-loop resume) but gated off via `LANGGRAPH_ENABLED=false` — confirmed accurate; Stage 6 addresses enablement.
- n8n is not deployed as a service anywhere (confirmed accurate) — the backend integration API n8n would call is real, tested, and unconditionally live regardless. Stage 8 addresses actual n8n deployment.
- Ollama is not connected (confirmed accurate — no Ollama service exists in either Compose file; `OpenAICompatibleTutorAdapter`'s default `base_url` merely *points at* Ollama's usual port, nothing is listening there today).

## Per-Stage Detail

### Stage 0 — Baseline, inventory, dependency map, and safety documentation — **ACTIVE**

- **Goal:** Establish ground truth about the current repository (not prior docs), classify every major capability, map dependencies, plan (but do not execute) Stage 1 cleanup.
- **Allowed changes:** Create/update documentation only.
- **Prohibited changes:** Any application code, migration, Docker/Compose, dependency, or environment-variable-behavior change; any deletion, move, or rename of application files; any commit or push.
- **Expected migrations:** None.
- **Expected affected services:** None.
- **Local test requirements:** Run existing tests read-only to establish a baseline (done — see `current-architecture-inventory.md` §12); do not fix failures found.
- **Production deployment impact:** None — no EC2 access was used or required.
- **Rollback checkpoint:** N/A (documentation-only; the branch itself is the checkpoint).
- **Definition of done:** All 6 documents listed in the Stage 0 task exist and are evidence-based (this document + 5 siblings). ✅ done as of this commit range.

### Stage 1 — Controlled Structural Reset *(re-scoped per Owner Migration Decisions — see top of this document)*

> **Revision history:** the original Stage 0 draft of this stage proposed creating empty/re-exporting packages ahead of need (removed in an earlier correction pass — that correction still holds, see below). A subsequent correction narrowed the stage to CI/test-fixture/Compose-validation only. **The product owner has now broadened it again**, via the Owner Migration Decisions above: Stage 1 is no longer a purely conservative, technical-safety-only cleanup — it now has explicit authority to remove application code, routes, tables, tests, n8n assets, and docs that are not relevant to the target architecture, determined by product relevance rather than technical entanglement alone. What has **not** changed: no empty package scaffolding, no reorganizing `ai_tutor/*` without an actual consuming capability, no production changes from Claude Code, and the mandatory preservation boundary (Owner Decision 2) stays untouched.

- **Goal:** Combine the previously-scoped CI/test-fixture/Compose-validation work with a genuine product-relevance review: determine which existing n8n workflows/diagrams/tests, application modules/routes/tables, and documentation are actually still wanted for the target architecture, and remove the confirmed-obsolete ones — while preserving the reusable generic infrastructure named in Owner Decision 5 and never touching the mandatory preservation boundary (Owner Decision 2) or production itself.
- **Allowed changes:**
  - Everything from the prior narrower draft: add `.github/workflows/ci.yml` running `pytest tests/unit -q` (the exact command Stage 0 validated — 1165 passed, 2 pre-existing failures) plus frontend `npm run typecheck`/`lint`/`test`; deliberately fix `tests/unit/test_openapi_snapshot.py`'s two failing assertions (test-fixture update, not an API change); validate both Compose files via `config`; resolve `docker-compose.yml.backup` (delete after user confirmation, per `deprecation-removal-plan.md` §4).
  - **New, per Owner Decisions 3-4:** a product-relevance review covering (a) the 6 n8n workflow files, diagrams, and their corresponding tests audited in Stage 0 (`deprecation-removal-plan.md` §3) — previously classified `KEEP`/`KEEP_AND_EXTEND` on technical grounds only (they're tested and wired); re-evaluate each against whether it's still wanted for the target Live Research architecture, not just whether it's technically live; (b) existing application modules, API routes, and database tables that Stage 0 classified as `IMPLEMENTED_AND_CONNECTED` but which may not serve the target architecture; (c) existing documentation, diagrams, and exports superseded by this Stage 0 documentation set or by the target architecture.
  - Items confirmed obsolete by this review may be removed: application code, API routes, database tables (via a new, additive-only migration that drops them — see "Expected migrations" below), tests, n8n workflows/diagrams, and documentation. Tests that existed only to protect a feature being intentionally removed are removed or replaced alongside it (Owner Decision 4) — a test passing is not, by itself, a reason to keep the feature it tests.
  - Reusable generic infrastructure named in Owner Decision 5 (auth, FastAPI, Next.js, Postgres, pgvector, TimescaleDB, Redis, Celery, Docker, Alembic, ports/adapters, the generic n8n-facing integration/auth contract) is preserved even while product-irrelevant application-level code built on top of it is removed.
- **Prohibited changes:**
  - Empty package scaffolding (`domain/knowledge/`, `application/tutor/`, etc. are still not created ahead of an actual capability needing them).
  - Any change to the mandatory preservation boundary (Owner Decision 2: current EC2 instance, Elastic IP/DNS, `researchstock.store`/`api.researchstock.store`, Caddy, HTTPS, Web→`localhost:3000`, API→`localhost:8080`, GitHub-based deployment).
  - Any production database reset (Owner Decision 6 — gated on new schema/migrations/bootstrap/admin-recreation/smoke tests being validated locally first; none of that exists yet, so a reset is not authorized in this stage).
  - Any production modification from Claude Code, ever (standing execution boundary).
  - Any edit to a released migration; any rename of `stock_research_core`; any change to Docker Compose service names.
- **Expected migrations:** Possibly yes — a change from the prior draft. If the product-relevance review confirms specific database tables are obsolete, Stage 1 may include a new, additive-in-the-chain migration that drops them. Any such migration must be written and verified (upgrade/downgrade/upgrade) against a **local, disposable** database first — treat a data-removing migration with the same "validate locally before applying to production" discipline as Owner Decision 6 requires for a full reset, even though a partial table drop is a smaller action than a full reset.
- **Expected affected services:** Depends on what the product-relevance review finds. At minimum, none at runtime (the CI/test-fixture/Compose-validation portion). If application modules/routes are removed, `finquest-api` and/or affected workers would need a rebuild — but Stage 1 itself does not deploy that rebuild to production; a human operator decides if/when to deploy Stage 1's result, following the runbook, same as any other stage.
- **Local test requirements:** `pytest tests/unit -q` clean (zero failures, including the deliberate OpenAPI-snapshot fix); the full test suite re-run after any module/test removal to confirm nothing still-wanted broke; frontend `lint`/`typecheck`/`test` clean.
- **Production deployment impact:** None directly from Claude Code (standing boundary). Whatever this stage produces is deployed later, manually, per the runbook — and only after local validation per Owner Decision 6 if it touches schema or data.
- **Rollback checkpoint:** Given the broadened scope, Stage 1 should land as a small number of separately reviewable PRs (e.g., CI/test-fixture first, product-relevance-review removals second) rather than one large PR — rollback of each is a Git revert per the runbook's rollback procedure.
- **Definition of done:** CI is green; `test_openapi_snapshot.py` has zero failures; both Compose files validate cleanly; `docker-compose.yml.backup` is resolved; a completed product-relevance review exists with an explicit, traceable list of what was removed and why (tied to Owner Decisions 3-4); no empty scaffolding was created; the mandatory preservation boundary and the reusable generic infrastructure (Owner Decisions 2 and 5) are both untouched; nothing was applied to production.

### Stage 2 — Production Docker image and worker-health correction *(contract expanded per correction pass)*

> **Superseded:** this Stage's scope was carried out and completed as **Phase A2** (see the "Phase A2 — Production Image and Worker-Health Correction — Detail" section above under the Master-Spec Phase Plan). This Stage 2 write-up is preserved as history/context, not as an open item.

- **Goal:** Correct production Docker image targets to match the `Dockerfile`'s own documented intent (only `finquest-api` and `finquest-worker-knowledge` need the heavier `ai` image; the other 3 workers don't need embedding dependencies), fix the worker-health-check contract so only the knowledge worker's healthcheck requires embedding-provider readiness, ensure the image actually contains the operational scripts it needs, and close the production-safety gap in the knowledge-base seed script.
- **Verified current state (Stage 0 correction-pass findings, grounding this stage's scope):** in `docker-compose.production.yml` today, **all 5** backend services (`finquest-api` + all 4 `finquest-worker-*`) are built with `target: ai`, uniformly — heavier than the `Dockerfile`'s own stage comment intends ("`base`... stays a small, network-free image for API/market/portfolio/evaluation workers. Only the knowledge worker... needs this stage"). Locally, `docker-compose.yml` correctly uses `target: base` for api/market/portfolio/default and `${KNOWLEDGE_WORKER_TARGET:-base}` for knowledge (defaulting to `base` even for knowledge unless overridden). The `Dockerfile` does not currently `COPY scripts ./scripts` into either stage. `cli/worker_status.py` has no CLI-flag support at all today (no `argparse`, no `--require-embedding`). `scripts/seed_finquest_knowledge_base.py` has a `--real-embeddings` flag but **no** guard analogous to `assert_embedding_provider_production_safe()` preventing a fake-embedding run against `FINQUEST_ENV=production`.
- **Allowed changes:**
  - `Dockerfile`: add `COPY scripts ./scripts` to the `base` stage, so seed/operational scripts are actually runnable inside a deployed container.
  - `docker-compose.production.yml`: change `target: ai` → `target: base` for `finquest-worker-market`, `finquest-worker-portfolio`, `finquest-worker-default`; keep `finquest-api` and `finquest-worker-knowledge` at `target: ai`.
  - `cli/worker_status.py`: add a `--require-embedding` flag so only the knowledge worker's Docker `HEALTHCHECK` invokes it with that flag — market/portfolio/default workers' healthchecks should not depend on embedding-provider initializability in a `base` image that was never meant to have those dependencies.
  - `scripts/seed_finquest_knowledge_base.py`: add a production-safety guard preventing a fake-embedding (i.e. non-`--real-embeddings`) run when `FINQUEST_ENV=production`, mirroring `assert_embedding_provider_production_safe()`'s existing pattern for the API.
  - Define or add the repeatable backup helper/runbook command described in `production-deployment-runbook.md` §5 — must exist and be exercised at least once **before Stage 3's ingestion** runs against production. (This is the only backup-automation work required by this stage — a full automated retention/off-server pipeline remains Stage 10's scope, not this stage's.)
- **Prohibited changes:** Application business logic; database schema; API surface.
- **Expected migrations:** None.
- **Expected affected services:** `finquest-api`, all 4 `finquest-worker-*` services (rebuild only, per the runbook's "only affected services" rule).
- **Local test requirements:** `docker compose build` succeeds locally for every affected service at its corrected target; new tests confirming (a) `worker_status.py --require-embedding` fails cleanly on a `base`-target container and passes on an `ai`-target one, (b) the KB seed script refuses fake embeddings when `FINQUEST_ENV=production`.
- **Production deployment impact:** Requires a real deploy — rebuild + recreate affected services only, per the runbook. Moving 3 services from `ai` to `base` should reduce image size/resource use, not regress functionality — confirm with a smoke test that market/portfolio/default workers still process jobs correctly afterward.
- **Rollback checkpoint:** Previous image tags/commit; rollback via the runbook's Git-consistent rollback procedure (§4) — a reverted commit and redeploy, not a direct old-commit checkout.
- **Definition of done:** All worker healthchecks pass consistently, with only the knowledge worker's healthcheck requiring embedding-provider readiness; `finquest-api` and `finquest-worker-knowledge` run the `ai` image, the other 3 workers run `base`; `scripts/` is present and runnable inside the deployed image; the KB seed script refuses fake embeddings in production without an explicit override; a documented backup command/helper exists and has been exercised at least once.

### Stage 3 — Markdown Knowledge Base foundation *(paths and approval contract corrected per correction pass)*

- **Goal:** Author and ingest a curated Markdown Knowledge Base corpus with front matter, a manifest, SHA-256 validation, and document versioning, using the ingestion pipeline that already exists.
- **Allowed changes:** New content under `knowledge/seed_documents/en/` with an accompanying `knowledge/seed_documents/manifest.json` — **not** `docs/knowledge/`; `docs/` is reserved for project/migration documentation, not tutor content, and this correction fixes an earlier inconsistent path; a manifest schema + validation script; an `approve_document` transition (service method + admin endpoint) to close the approval-workflow gap identified in `architecture-migration-plan.md` §2.17; optionally an S3-compatible storage adapter behind a new port.
- **Prohibited changes:** Changing the existing hybrid-retrieval or embedding logic; changing how curriculum-derived knowledge is ingested (additive only).
- **Expected migrations:** Possibly one, only if the approval-workflow transition needs a new column/state (current fields likely suffice — verify before deciding a migration is needed).
- **Expected affected services:** `finquest-worker-knowledge` (re-ingestion), `finquest-api` (new admin endpoint).
- **Local test requirements:** New tests for the manifest validator, the approval transition, idempotent re-ingestion (running ingestion twice against an unchanged corpus produces no duplicate/re-archived rows), and retrieval scoped to the approved subset of the corpus.
- **Production deployment impact:** Requires running an ingestion job against production data — must be preceded by a backup using the Stage 2 backup helper, and must run with a real (non-fake) embedding provider, enforced by the Stage 2 production-safety guard on the seed script.
- **Rollback checkpoint:** Pre-ingestion DB backup; ingestion is additive (new document rows), so rollback is "delete/archive the newly ingested documents," not a schema rollback.
- **Definition of done (approval is a deliberate editorial decision, not automatic):**
  - Exactly 15 substantive Markdown documents exist under `knowledge/seed_documents/en/`.
  - Every document has valid front matter matching the defined schema.
  - `knowledge/seed_documents/manifest.json` is valid and every listed SHA-256 hash matches its document's actual content.
  - The validation script passes against the full corpus.
  - Only documents whose factual claims have been source-verified by a human reviewer are transitioned to `APPROVED`; every other document remains `DRAFT` in a state recorded as `draft_requires_source_review` — approval is never a side effect of ingestion.
  - No unapproved document is ever returned by learner-facing retrieval (already enforced today by `hybrid_search`'s `approval_status == APPROVED` filter — this stage must not weaken that filter).
  - Ingestion is idempotent: re-running it against an unchanged corpus produces no duplicate or re-archived documents.
  - New retrieval tests cover the approved subset of the corpus specifically (not just curriculum-derived content).

### Stage 4 — Ollama grounded Tutor

- **Goal:** Make `OpenAICompatibleTutorAdapter` (pointed at a real Ollama instance) the default tutor provider in target environments, with structured responses, citations, and defined failure behavior — while keeping SentenceTransformer embeddings as-is (per the user's own instruction).
- **Allowed changes:** New Ollama service in Compose (opt-in, not replacing the extractive default in every environment simultaneously); a new integration test exercising the adapter against a real or containerized Ollama; documented resource sizing.
- **Prohibited changes:** Changing the embedding provider; changing the citation-verification/guardrail logic (reuse it — it already validates cited chunk IDs against retrieval evidence, model-agnostically).
- **Expected migrations:** None expected.
- **Expected affected services:** New `ollama` Compose service; `finquest-api` (env var change to switch provider, no code change needed — the adapter already exists).
- **Local test requirements:** New `tests/integration/test_openai_compatible_tutor_ollama.py`-style test (does not exist today — a confirmed gap); full guardrail/evaluation suite (`finquest-safety-v1`, `finquest-rag-core-v1`) re-run against real Ollama output.
- **Production deployment impact:** Resource sizing risk (see `architecture-migration-plan.md` risk table) — must be load-tested on a non-production host first.
- **Rollback checkpoint:** The flag flip (`TUTOR_MODEL_PROVIDER`) is instantly reversible — rollback is an env var change plus service restart, not a code rollback.
- **Definition of done:** Ollama answers pass the full guardrail + evaluation suite at parity with (or better than) the extractive tutor's safety profile.

### Stage 5 — Guardrails and Knowledge Sufficiency Gate

- **Goal:** Build a named, scored Knowledge Sufficiency Gate (replacing today's implicit "any citations vs. none" check) and, optionally, a distinct retrieval-stage guardrail component (today folded into the retriever).
- **Allowed changes:** New `KnowledgeSufficiencyGate` port/class in `application/ai_tutor/` (or its Stage-1 successor location); threshold configuration; current-information classification as a precursor to Stage 7 routing.
- **Prohibited changes:** Existing input/output guardrail logic (extend, don't replace) — it is tested and production-safe today.
- **Expected migrations:** Possibly one, if sufficiency decisions need to be persisted/audited (recommended, for the same reasons `tutor_guardrail_decisions` exists).
- **Expected affected services:** `finquest-api`.
- **Local test requirements:** New unit tests for the gate's threshold logic; full `test_tutor_guardrails.py` must still pass unmodified (regression check).
- **Production deployment impact:** Low — additive gate, existing fallback path unchanged.
- **Rollback checkpoint:** Feature-flag the gate the same way every other Stage 4-6 feature is flagged, so rollback is a config change.
- **Definition of done:** Gate correctly abstains on genuinely insufficient evidence and correctly answers on sufficient evidence, verified against the existing evaluation suites plus new threshold-boundary cases.

### Stage 6 — Top-level LangGraph orchestration (enablement)

- **Goal:** Enable `LANGGRAPH_ENABLED=true` in a real (first staging, then production) environment; fix the pre-existing `test_openapi_snapshot.py` drift deliberately as part of this stage (since this is the stage that intentionally finalizes the `/api/v1/coach` surface).
- **Allowed changes:** Flag flip; OpenAPI snapshot update; any final polish to the 22-node graph found necessary under real (non-fake) load; frontend capability-detection so the Coach UI degrades gracefully if the flag is ever off in one environment but not another (see `migration-dependency-map.md` §5 risk).
- **Prohibited changes:** The underlying tutor/scenario/portfolio/adaptive services the graph calls (reuse them; this stage is about turning the orchestrator on, not rewriting its dependents).
- **Expected migrations:** None expected (0010 already created the audit tables; LangGraph's own checkpoint tables are created via the `learning_orchestrator_admin --setup-checkpointer` CLI step, which must be run once against the target DB before enabling).
- **Expected affected services:** `finquest-api` (checkpointer pool opens at startup once enabled — capacity implication per risk table).
- **Local test requirements:** Full `tests/integration/test_orchestrator_*` and `test_langgraph_postgres_checkpointer.py` against local Postgres; canary-style enablement in staging before production.
- **Production deployment impact:** Medium — first-ever production enablement of this code path; must follow a canary plan, not a direct flip (per risk table).
- **Rollback checkpoint:** Flag flip back to `false`; checkpoint tables can remain (harmless if unused) — no destructive rollback needed.
- **Definition of done:** Coach is live in production, OpenAPI snapshot test passes again (deliberately updated), no capacity regression observed on `/metrics`.

### Stage 7 — Live Research domain

- **Goal:** Build research jobs, evidence normalization, source trust/scoring, callbacks, and synthesis contracts as a new domain, reusing the existing `BackgroundJobService`/Celery job pattern and the LangGraph subgraph pattern.
- **Allowed changes:** New `domain/live_research/`, `application/live_research/`, `infrastructure/live_research/` packages (per target repository structure); new `BackgroundJobType` entries; a new LangGraph subgraph analogous to existing ones.
- **Prohibited changes:** Existing job types/queues (additive only).
- **Expected migrations:** Yes — new tables for research jobs/evidence/sources.
- **Expected affected services:** `finquest-api`, likely a new or repurposed worker queue.
- **Local test requirements:** Full new test suite mirroring the existing per-capability pattern (unit + integration, architecture tests).
- **Production deployment impact:** Medium — new schema, new job type, no existing behavior touched.
- **Rollback checkpoint:** New migration is additive; rollback via `alembic downgrade` to pre-Stage-7 revision if needed before any data depends on the new tables.
- **Definition of done:** A research job can be submitted, evidence normalized and scored, and a synthesized answer produced with verifiable citations — end-to-end, in a non-production environment first.

### Stage 8 — n8n, Perplexity, SEC, and structured market data

- **Goal:** Actually deploy n8n (or confirm the decision not to self-host it and use the existing generic integration API from an externally-managed n8n instead); add Perplexity, SEC/filings, and additional market-data provider adapters.
- **Allowed changes:** Extend (not replace) the 5 job-trigger n8n workflows for new Live Research job types; new provider adapters behind the existing `MarketDataProviderPort`-style pattern; new Perplexity adapter behind a new port.
- **Prohibited changes:** The existing yfinance adapter and its tests (additive new providers only); the existing integration-auth/idempotency contract (extend its allowed-job-types, don't redesign it).
- **Expected migrations:** Possibly none (integration schema already supports arbitrary `BackgroundJobType`s) — verify before assuming.
- **Expected affected services:** Possibly a new `n8n` Compose service, if self-hosting is chosen.
- **Local test requirements:** `test_n8n_workflow_contracts.py` extended for new workflow files; new provider-adapter tests.
- **Production deployment impact:** Medium-high if n8n is newly self-hosted (new service, new attack surface — needs its own security review); low if using an externally-managed n8n instance.
- **Rollback checkpoint:** New workflows are independently importable/removable in n8n itself; backend changes are additive.
- **Definition of done:** At least one real external research signal (Perplexity or SEC) flows end-to-end through a job trigger to a synthesized, cited answer.

### Stage 9 — Learning Engine expansion

- **Goal:** Course/Track/Unit/Concept mapping (reusing `LearningPath`/`LearningModule`/`Lesson`/`Skill` where they already satisfy the target vocabulary), misconception detection, gamification, spaced-repetition refinement, English/Hebrew bilingual support.
- **Allowed changes:** New `Concept`/`Unit` tiers if genuinely needed (per gap matrix — evaluate before adding, since `Module`/`Skill` may already suffice); a real misconception-detection service; real XP/streak/achievement computation; i18n infrastructure (backend localized-content model + frontend `dir`/locale support).
- **Prohibited changes:** Renaming `LearningPath`→`Course` etc. without a proven need (per user's explicit instruction) — prefer additive concepts or documented vocabulary mapping.
- **Expected migrations:** Yes — new tables for achievements, misconception-detection outputs (if the schema needs new fields beyond what exists), localized content.
- **Expected affected services:** `finquest-api`, `finquest-web` (major frontend work for RTL/i18n).
- **Local test requirements:** Full test suite for each new sub-feature; frontend a11y suite re-run with RTL routes added.
- **Production deployment impact:** Medium — mostly additive, but RTL/i18n touches shared layout code broadly.
- **Rollback checkpoint:** Per-feature flags recommended (matching the existing pattern) so each of gamification/misconceptions/i18n can roll back independently.
- **Definition of done:** All four sub-features (concept mapping decision, misconceptions, gamification, bilingual) are live and independently toggleable.

### Stage 10 — Final production migration and hardening

- **Goal:** Backups, restore-test verification, security review, monitoring, performance validation, release verification across the whole migrated system.
- **Allowed changes:** Operational/config hardening; no new features.
- **Prohibited changes:** New feature work (belongs in earlier stages).
- **Expected migrations:** None new, but every prior stage's migrations must be verified restorable from backup.
- **Expected affected services:** All.
- **Local test requirements:** Full test suite, full evaluation suite, a documented restore-from-backup drill performed at least once against a non-production copy.
- **Production deployment impact:** High-visibility but should be low-risk if every prior stage's rollback checkpoints were honored.
- **Rollback checkpoint:** Full backup taken immediately before this stage's final production changes.
- **Definition of done:** A completed restore drill, a passing security review, monitoring dashboards covering every new subsystem, and sign-off that the target architecture (Learning + Knowledge/Tutor + Live Research engines, bilingual, S3 storage, observability, security, testing) is met.

---

## Stage 1 Entry Criteria (recommended scope — not implemented in Stage 0)

*Revised twice: first to drop package creation/re-export scaffolding and the cosmetic test-file move (an earlier correction pass), then broadened again per the Owner Migration Decisions above into a Controlled Structural Reset. Items below are split into "known now" (concrete, from the CI/test-fixture/Compose-validation portion) and "determined by the product-relevance review" (Stage 1's own first work item under the new scope — Stage 0 does not have the product-relevance information to name these specifically).*

**Known now:**
- **Exact files proposed for deletion:** `docker-compose.yml.backup` — pending explicit user confirmation that its one-line `HOSTNAME` divergence from the current `docker-compose.yml` reflects an intentional, already-adopted change (see `deprecation-removal-plan.md` §4).
- **Exact files proposed for movement:** None identified yet outside the review below.
- **Exact modules proposed for creation:** None under `src/`. Only `.github/workflows/ci.yml` (new file, CI configuration, not an application package) — still holds; empty package scaffolding remains out of scope per Owner Decision 7.
- **Exact compatibility measures:** None needed for the known-now portion — no package move is happening.
- **Exact tests required before any change:** `pytest tests/unit -q` — the exact command Stage 0 executed (1165 passed, 2 pre-existing `test_openapi_snapshot.py` failures); not the same invocation as `pytest -m "not integration"` (see `current-architecture-inventory.md` §12.1). The full `pytest -m integration` suite was **not run to completion in Stage 0** (§12.3) — Stage 1's CI should budget a dedicated, multi-hour run before relying on it as a gate. Full frontend `lint`/`typecheck`/`test` (34/34 files, 154/154 tests, all passing, 74.95s).
- **Exact tests required after the OpenAPI-snapshot fix:** `pytest tests/unit -q` with **zero** failures.
- **Whether any migration is required (known-now portion):** No.
- **Which Docker services would be affected (known-now portion):** None at runtime.
- **Rollback approach (known-now portion):** A Git revert of the relevant PR per the runbook's rollback procedure (§4). No data migration involved.

**Determined by the product-relevance review (to be produced as Stage 1's first deliverable, not assumed here):**
- **Exact files/modules/n8n-workflows/docs proposed for removal:** Not enumerated in Stage 0 — this requires the product owner's judgment (via whoever runs Stage 1) about which of the `IMPLEMENTED_AND_CONNECTED`/`KEEP`/`KEEP_AND_EXTEND` items in `deprecation-removal-plan.md` and `architecture-migration-plan.md` §2 are still wanted for the target architecture. Stage 0 explicitly does not have the authority or information to name these; naming them without that judgment would just be re-introducing the "technical entanglement ≠ product relevance" mistake Owner Decision 4 calls out.
- **Exact tests proposed for removal:** Whichever tests exist solely to protect a feature the review confirms as obsolete — determined together with the feature list above, not separately.
- **Whether any migration is required:** Possibly — only if the review confirms specific database tables are obsolete. Any such migration is additive-only in the chain (drops tables, doesn't renumber or edit existing migrations) and must be validated locally (upgrade/downgrade/upgrade against a disposable database) before any production application is even considered.
- **Which Docker services would be affected:** Only ones whose code the review actually removes — cannot be named until the review completes.
- **Rollback approach:** Same Git-revert discipline as above, plus — if a migration is involved — the runbook's migration-aware rollback branching (§4): confirm whether the migration ran before deciding between a downgrade and a backup restore.
