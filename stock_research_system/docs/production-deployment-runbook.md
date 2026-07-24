# FinQuest Production Deployment Runbook

## Execution Boundary (read this first)

- **Claude Code has no EC2 access** — no SSH, no production environment variables, no production database, no production secrets, and no ability to deploy. Every command below that touches EC2 is documented for a **human operator** to run manually; none of it has been executed by Claude Code, and no claim in any Stage 0 document should be read as implying otherwise.
- All application changes are developed and tested **locally** (or via CI once Stage 1 adds it), never edited directly on the EC2 host.
- **GitHub `main` is the deployment source of truth.** EC2 only ever runs `git pull` against `main` — it never receives a patch, a hotfix edited in place, or a branch other than `main`.
- Deployment to EC2 is performed **manually** by a human, following the steps below, after local review + local tests + a Git commit + a push + a merge to `main`.
- `.env` (and any `.env.production`, `.env.local`, etc.) must **never** be committed — `.gitignore` already excludes `.env` and `.env.backup`; the `.example` files are the only env-related files meant to be tracked.
- **Backups are required before any migration or data transformation** — no exceptions, including "small" migrations.
- Only the services actually affected by a change should be rebuilt and recreated — never `docker compose up -d --build` for the entire stack as a default reflex.
- Builds should be run **sequentially**, not in parallel, given the EC2 host's limited resources (it runs Postgres, Redis, the API, the web app, and 4 Celery workers simultaneously already).
- **Health checks are not enough.** A service reporting `healthy` only proves the process is up — it does not prove the specific feature that changed still works. Every deploy must include a feature-specific smoke test appropriate to what changed (see §5).
- **Rollback must be commit-based and backup-aware** — rolling back code without considering whether a migration ran since the last-known-good commit can leave the schema and the code mismatched. Always check migration state before rolling back code. The normal rollback path is a **Git revert**, not a direct checkout of an old commit on the server (see §3).
- **The EC2 checkout must always remain clean** (`git status` shows no local modifications, no untracked tracked-file edits). Documentation and status records are never edited directly on the EC2 checkout — see §2's step 11 and §4.

---

## 1. Current Production Architecture (must be preserved unless a later approved stage explicitly changes it)

- AWS EC2, Ubuntu
- Public domains: `https://researchstock.store` (web), `https://api.researchstock.store` (API)
- Caddy on the EC2 host, reverse-proxying: web → `127.0.0.1:3000`, API → `127.0.0.1:8080`
- Docker Compose production deployment (`docker-compose.production.yml`)
- Services: `stock-db` (TimescaleDB+pgvector), `redis`, `finquest-api` (FastAPI), `finquest-web` (Next.js), `finquest-worker-{market,portfolio,knowledge,default}` (Celery)
- Alembic migrations, currently at head `0011_ragas_learning_quality`
- Existing HTTPS certificates (managed by Caddy)
- Authentication with refresh tokens and ADMIN account support

**Nothing in this migration requires replacing the domain or recreating the production server from scratch.** Every stage in `migration-status.md` is designed to be an incremental change to this existing architecture.

---

## 2. Conventions — the `dc()` helper

**Every production Compose command in this runbook must explicitly include both `--env-file .env` and `-f docker-compose.production.yml`.** Relying on Compose's default file/env-file resolution on the production host is exactly the kind of implicit behavior this runbook exists to prevent — `docker-compose.production.yml` interpolates image targets, ports, and other values from `.env` (confirmed in Stage 0: e.g. `target: ai` is hardcoded per service in production today, but other values such as `KNOWLEDGE_WORKER_TARGET` are `.env`-driven in the local compose file, and production must not silently fall back to defaults meant for local dev).

Define this helper once per EC2 shell session (or in the operator's `~/.bashrc`/a sourced ops script — not committed to the repository, since it's a local shell convenience, not application config):

```bash
dc() {
  docker compose \
    --env-file .env \
    -f docker-compose.production.yml \
    "$@"
}
```

Every `docker compose ...` invocation against production in this runbook is written as `dc ...` below and assumes this helper is defined. **Never** run a bare `docker compose -f docker-compose.production.yml ...` without `--env-file .env` on the production host.

---

## 3. Standard Flow

### Local (every change, every stage)

1. Create a stage branch (e.g., `migration/stage-0X-<name>`) off `main`.
2. Implement the change, scoped to that stage's "Allowed changes" (see `migration-status.md`).
3. Run tests:
   - Backend: `pytest tests/unit -q` (always — this is the command actually validated in Stage 0: 1165 passed, 2 pre-existing failures); `pytest tests/integration -m integration -q` (if local `stock-db`/`redis` are running — budget significant time for this, see `current-architecture-inventory.md` §12.3 for why). Once Stage 1 defines CI, use whatever exact command CI runs — do not assume `pytest -m "not integration"` is equivalent to `pytest tests/unit -q` without verifying it (the former also collects the 4 loose top-level test files under `tests/`).
   - Frontend: `npm run typecheck && npm run lint && npm run test` (always); `npm run test:e2e` (if the full local stack is running).
4. Inspect `git diff` / `git status` — confirm only the intended files changed, and that no `.env`-shaped file or secret is staged.
5. Commit, with a message describing why, not just what.
6. Push the branch.
7. Open a PR for review.
8. Merge to `main` only after review and a green CI run (once Stage 1 adds CI).

### EC2 (manual, human-operated, after merge to `main`)

1. **Verify clean working tree** on the EC2 checkout: `git status` must show no uncommitted local changes before pulling. If it doesn't, stop and investigate — someone may have made an undocumented hotfix (or a documentation edit — see §4) directly on the server, which itself is a process violation to flag, not silently overwrite.
2. **Record the current commit** (`git rev-parse HEAD`) before doing anything else — this is the rollback target if the deploy needs to be reverted.
3. **Create a backup when required** (any migration, any data transformation, any Stage marked "requires backup" in `migration-status.md`): a `pg_dump` of the production database to a location outside the container/host's ephemeral storage, timestamped and named with the pre-deploy commit SHA for traceability. See §6 for the current state of backup tooling.
4. **Fetch and pull `main` with `--ff-only`**: `git fetch origin && git pull --ff-only origin main`. A non-fast-forward result means the local EC2 checkout has diverged — stop and investigate before forcing anything.
5. **Validate Compose** before touching running services: `dc config` (catches YAML/interpolation errors without starting anything).
6. **Run migrations explicitly**, as a separate, observable step — never implicitly via a service's own startup code: `dc exec finquest-api python -m alembic upgrade head` (or an equivalent one-off run if `finquest-api` isn't already up on the new image). Confirm with `dc exec finquest-api python -m alembic current` afterward.
7. **Build affected services only**, sequentially: `dc build <service>` for each service actually changed by this stage — never rebuild all 8 services as a default.
8. **Recreate affected services only**: `dc up -d --no-deps <service>` for each rebuilt service — `--no-deps` avoids an unintended cascade restart of unrelated services.
9. **Verify health/readiness**: `dc ps` (all `healthy`), plus `GET https://api.researchstock.store/health` and `/ready` if the stage touched anything they check.
10. **Run stage-specific smoke tests** — a curl/browser check of the *specific feature that changed*, not just "the site loads." Examples: after Stage 2 (worker health), directly invoke `worker_status` inside each worker container; after Stage 4 (Ollama), send one real tutor question and confirm a grounded, cited answer comes back; after Stage 6 (LangGraph enablement), open the Coach UI and complete one full turn.
11. **Record the deployed commit** — append the SHA now running, the timestamp, and who deployed it to an **operator-owned log outside the Git checkout**, e.g. `/home/ubuntu/deployments/finquest-deployments.log`. **Do not edit any tracked file in the EC2 checkout to record this** (including `migration-status.md`'s "Current Production Commit" line) — the EC2 checkout must stay clean (see Execution Boundary). If the tracked docs need updating to reflect a new deployed state, do that **locally**, commit, push, and merge through the normal PR flow like any other change — never as a direct edit on the server.

---

## 4. Rollback

Rollback is **Git-consistent, commit-based, and backup-aware** — never a direct checkout of an old commit on the production server as the normal procedure, and never `git reset --hard` on production `main`.

### Normal rollback path

1. **Create a revert commit locally** (`git revert <bad-commit-or-range>`) on a new branch off `main` — this preserves history and produces a reviewable, normal commit, exactly like any other change.
2. **Push it.**
3. **Open a PR, review it, and merge it into `main`** — a rollback is a deploy like any other and goes through the same review gate; do not skip review just because it's urgent.
4. **On EC2: pull `main` with `--ff-only`** (`git fetch origin && git pull --ff-only origin main`) — the exact same step as a forward deploy (§3, EC2 step 4).
5. **Rebuild and recreate only the affected services** (§3, EC2 steps 7-8), using `dc`.
6. **Verify health and run the same feature-specific smoke test** that would have validated the original forward deploy, to confirm the revert actually restored working behavior (§3, EC2 steps 9-10).

### Migration-aware branching before starting a rollback

Before step 1 above, determine whether a migration ran as part of the deploy being rolled back (check the operator deployment log from §3 EC2 step 11, and `dc exec finquest-api python -m alembic current` now vs. what it was before):

- If **no migration ran**: the revert-commit path above is sufficient on its own.
- If **a migration ran**: a code-only revert is not sufficient — the schema is now ahead of the old code's expectations. Before or alongside the revert commit, either (a) `dc exec finquest-api python -m alembic downgrade <prior-revision>` (only safe if the migration is confirmed reversible and no new data depends on the new schema yet), or (b) restore the pre-deploy backup taken in §3 EC2 step 3, accepting the data-loss window between backup and rollback. Decide which before starting — don't discover this mid-rollback.

### Emergency exception (temporary only, must return to `main` afterward)

A direct `git checkout <previous-commit>` on the EC2 host **may** be used, but only as a **clearly labeled, temporary emergency measure** when production is actively broken and there is no time to wait for a revert PR to be reviewed and merged (e.g., an active incident). If this is used:

- Label it explicitly in the operator deployment log as an emergency temporary checkout, with the reason and timestamp.
- This leaves the EC2 checkout in a detached-HEAD state that **does not match `main`** — this is a known, temporary, tracked deviation, not a new normal state.
- **A revert commit must still be created, pushed, reviewed, and merged into `main` afterward**, and the EC2 checkout must then be moved back onto `main` (`git checkout main && git pull --ff-only origin main`) as soon as the incident is resolved — the emergency checkout is never the final state.
- `git reset --hard` on production `main` is **never** an acceptable substitute for this — it rewrites the branch pointer in a way that can silently discard commits other people have already based work on. If a hard reset is ever genuinely necessary, it requires explicit, separate user authorization at the time, not standing permission from this runbook.

---

## 5. Backup Requirements

- Required before: any Alembic migration, any bulk data transformation/seed script run against production, any Stage explicitly marked as touching schema in `migration-status.md`.
- A backup is not "required before every deploy" if a given deploy is pure application-code-with-no-migration — but when in doubt, take one; it is cheap relative to the cost of an unrecoverable mistake.
- Backups must be stored outside the container/host's own ephemeral disk (i.e., not just inside the `stock-db` container's writable layer).
- **Current state (accurate as of Stage 0):** the runbook already *requires* a verified manual backup before every production migration or data transformation (the process described above) — but **no backup automation exists in this repository today** (confirmed in Stage 0 — see `architecture-migration-plan.md` risk table, "current data-loss risk"). **Stage 2** should define or add a repeatable backup helper/runbook command (e.g., a documented `pg_dump` one-liner or script, not necessarily a cron job) — this must exist and be exercised at least once **before Stage 3's knowledge-base ingestion** runs against production, since that is the first stage that writes a meaningful volume of new data. A full **automated** retention/off-server backup pipeline and a verified restore drill remain in scope no later than **Stage 10**. Do not read this runbook as claiming backup automation is implemented today — it is not.

---

## 6. Feature-Specific Smoke Tests (grows with each stage)

| Stage | What changed | Smoke test |
|---|---|---|
| 2 | Worker health/image targets | `dc exec finquest-worker-market python -m stock_research_core.cli.worker_status` (repeat per worker) |
| 3 | Knowledge Base corpus | Ask the tutor a question whose answer requires the newly ingested content; confirm citations reference the new documents |
| 4 | Ollama tutor | Ask a real tutor question; confirm the response is grounded, cited, and did not silently fall back to the extractive tutor (check `tutor_model_provider` in the response metadata / logs) |
| 5 | Sufficiency gate | Ask a question with no supporting knowledge; confirm a clean abstention, not a hallucinated answer |
| 6 | LangGraph coach | Complete one full Coach conversation turn in the browser against production, including one action-approval interaction |
| 7 | Live Research | Submit one real research job end-to-end; confirm a synthesized, cited result |
| 8 | n8n / providers | Trigger one real n8n workflow against production; confirm the job completes and the callback/poll reflects it |
| 9 | Learning expansion | Exercise one new/changed learner-facing screen in the browser, including an RTL check if bilingual support shipped |
| 10 | Hardening | Full smoke suite above, plus a restore-from-backup drill against a non-production copy |

---

## 7. What Must Never Happen (repeated for emphasis)

- No SSH session, migration, or deploy command from Claude Code against the real EC2 host.
- No committed `.env`/secret file.
- No `docker compose up -d --build` against the full stack as a reflex — always name the affected services, and always through `dc` (with `--env-file .env -f docker-compose.production.yml`), never a bare `docker compose` invocation.
- No migration run implicitly via a service's own startup path in production — always the explicit `alembic upgrade head` step, observed and confirmed.
- No direct edit of a tracked file (including `migration-status.md`) on the EC2 checkout, ever — deployment records go to an operator-owned log outside the checkout; documentation changes go through the normal local-commit-push-PR flow.
- No `git reset --hard` on production `main` as the normal rollback procedure — the normal path is a reviewed revert commit (§4); a temporary emergency checkout is the only sanctioned exception, and it must be resolved back onto `main` afterward.
- No rollback without first checking whether a migration ran since the commit being rolled back to.
