# FinQuest n8n Integration (Phase 11)

n8n's role here is **orchestration only**: trigger a FinQuest background
job, pass validated parameters, poll for completion, branch on the
result, and produce an operational summary. n8n never touches the
FinQuest database, never re-implements market ingestion, portfolio
valuation, knowledge ingestion, retrieval, or grading logic, and never
receives a database URL, a Redis URL, or a learner's data.

See `credentials.example.md` for how to create the FinQuest integration
client and the matching n8n credential (no real secrets are ever
committed to this directory or to a workflow's JSON export).

## Workflows

| File | Job type | Default trigger |
|---|---|---|
| `workflows/tracked-market-refresh.json` | `TRACKED_MARKET_REFRESH` | Daily 06:00 |
| `workflows/portfolio-valuation.json` | `PORTFOLIO_BATCH_VALUATION` (`all_active_portfolios: true`) | Daily 07:00 |
| `workflows/knowledge-refresh.json` | `CURRICULUM_KNOWLEDGE_REFRESH` | Weekly (Sun 03:00) or manual |
| `workflows/retrieval-evaluation.json` | `RETRIEVAL_EVALUATION` | Weekly (Sun 04:00) or manual |
| `workflows/system-readiness-watch.json` | *(none - calls `/ready` only)* | Hourly |
| `workflows/quality-evaluation.json` | `RAGAS_QUALITY_EVALUATION` (+ optional `QUALITY_BASELINE_COMPARISON`) | Weekly (Sun 05:00) or manual |

## Shared shape (the first four workflows)

```text
Trigger (schedule/manual)
  -> Build Request            (generates idempotencyKey + externalRequestId)
  -> Trigger FinQuest Job     (POST /api/v1/integrations/n8n/jobs, 202 Accepted)
  -> Init Polling State       (extracts job_id; attempt=0, maxAttempts=40, waitSeconds=15)
  -> Wait Before Poll         (bounded wait - 15s per iteration)
  -> Poll Job Status          (GET /api/v1/integrations/n8n/jobs/{job_id})
  -> Merge Polling State
  -> Is Terminal Or Timed Out?
       yes -> Build Structured Summary -> Notify (not implemented in this phase)
       no  -> Increment Attempt -> (loops back to Wait Before Poll)
```

- **Bounded polling**: `maxAttempts=40` * `waitSeconds=15` = a 10-minute
  maximum polling duration per execution. Adjust both via the `Init
  Polling State` node if a job type legitimately needs longer.
- **Terminal states**: `SUCCEEDED`, `FAILED`, `CANCELLED`, `SKIPPED`. A
  run that never reaches one of these within `maxAttempts` produces a
  `POLLING_TIMEOUT` summary instead of looping forever.
- **Idempotency**: `idempotencyKey` is derived from the job type, the
  n8n workflow ID, and the current hour (`YYYY-MM-DDTHH`) - re-running
  the same workflow within the same hour (e.g. a manual retry) returns
  the same canonical job instead of creating a duplicate. `externalRequestId`
  is unique per execution and is what FinQuest's replay protection
  (`integration_requests`) keys on.
- **The final "Notify" node is a documented placeholder** (a no-op) -
  connect a Slack/Email node there in a future phase; email/push
  notifications are explicitly out of scope for Phase 11.

## Quality Evaluation (Phase 13)

`workflows/quality-evaluation.json` follows the same shape, plus an
explicit `Trigger FinQuest Job` HTTP node between `Build Request` and
`Init Polling State` (the other four workflows' `Init Polling State`
reads `job_id` off the response of a trigger call that is not itself
present as a node in this export - a pre-existing gap from Phase 11,
out of scope to change here) and one extra branch after the summary:
if `FINQUEST_EVAL_BASELINE_ID` is set, it fires a
`QUALITY_BASELINE_COMPARISON` job for the run that just completed
before reaching Notify; leaving that variable unset skips the branch
entirely. It never approves a baseline and never deploys or rolls back
anything - both remain explicit, separate, human-triggered actions.
Set `FINQUEST_EVAL_SUITE_ID` (required) and optionally
`FINQUEST_EVAL_MODE`/`FINQUEST_EVAL_SUITE_VERSION`/
`FINQUEST_EVAL_BASELINE_ID` as n8n environment variables.

## System Readiness Watch

Calls the integration-safe `GET /api/v1/integrations/n8n/ready` endpoint
hourly and evaluates `ready`/`database_ready`/`redis_ready`/
`migration_up_to_date` into a `HEALTHY`/`UNHEALTHY` structured status.
No polling loop (readiness is synchronous), no PostgreSQL access.

## Manual triggering without n8n

`examples/trigger-job.ps1` and `examples/trigger-job.sh` call the same
integration API directly - useful for testing the API contract or for
CI, without needing an n8n instance running.

## Local validation

`tests/integration/test_n8n_workflow_contracts.py` validates every file
in `workflows/`: valid JSON, no embedded credentials, no PostgreSQL
node, a bounded polling loop, terminal-state handling, and a job type
that actually exists in `BackgroundJobType`. Where a local n8n container
is available, the same test additionally imports each workflow via
n8n's REST API and asserts it loads without error - this part is skipped
(not failed) when no n8n instance is reachable.
