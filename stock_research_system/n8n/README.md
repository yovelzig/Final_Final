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
| `workflows/live-research-run.json` | `LIVE_RESEARCH_RUN_EXECUTION` | Webhook (production) or Manual Trigger (dev/testing only) |

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

## Live Research Run (Phase G2C)

`workflows/live-research-run.json` is the one workflow authorized to
trigger `LIVE_RESEARCH_RUN_EXECUTION`. It never calls Perplexity or SEC
directly - it only calls the FinQuest integration API, exactly like every
other workflow in this directory. It is inert until all four activation
gates in `docs/migration-status.md`'s "Phase G2C" section are satisfied
(job registry allows `N8N`, the calling `IntegrationClient` has the
permission, `LIVE_RESEARCH_JOBS_ENABLED=true`, and the scope's required
provider(s) are enabled).

### Two trigger paths, one validation contract

- **Webhook Trigger (production).** Requires Header Auth (see "Webhook
  authentication" below). `invocation_id` is **mandatory** on this path -
  a missing `invocation_id` fails validation before any `POST /jobs` call
  is made. FinQuest never sees a request without one.
- **Manual Trigger (dev/testing only).** May generate a temporary
  `invocation_id` (a UUID, stable only for that one execution, using a
  pure-JavaScript generator - no Node built-in module dependency, since
  n8n Cloud code nodes run in a restricted sandbox) when none is
  supplied. This path must never be used in production, and it never
  weakens the Webhook Trigger's own mandatory validation - the check is
  gated on `$execution.mode === 'manual'`, which the Webhook path can
  never satisfy.

Both paths feed the same `Validate / Build Request` node, which also
enforces the exact per-scope parameter contract below before building the
request body - a request that fails validation never reaches
`Trigger FinQuest Job`. `invocation_id` is additionally required to be a
canonical UUID (any surrounding whitespace is trimmed, casing is
normalized to lowercase, and a malformed value fails validation) whether
it was supplied on the Webhook path or generated on the Manual Trigger
path. Every returned `json` - success or validation error - carries an
explicit `isManual` flag, so downstream nodes route on it directly rather
than re-deriving `$execution.mode` themselves.

**Final correction - minimal request validation only.** `Validate / Build
Request` never duplicates the FinQuest backend's Pydantic model. It
validates only safety/routing-critical fields before `POST /jobs`:
`invocation_id` is a canonical UUID, `scope` is one of the five supported
scopes (`MARKET_DATA_SNAPSHOT` is always rejected), `original_question` is
a non-blank string (trimmed), `GENERAL_QUESTION` includes no subject,
every other scope includes exactly one of `subject_security_id`/
`subject_raw_text` (a blank `subject_raw_text` becomes absent - never
treated as a provided subject), and the required SEC fields
(`sec_cik`, and for `COMPANY_OVERVIEW` also a non-empty `sec_concepts`)
are present for the SEC scopes. The FinQuest backend remains authoritative
for everything else - exact length limits, complete SEC CIK validation,
`sec_concepts` shape/deduplication, and every other parameter constraint.
A request that passes this minimal n8n-side check but is still rejected
by the backend is handled gracefully post-`POST` rather than causing a
crash - see "FinQuest 4xx/5xx never crashes the run" below.

**Safe input envelope.** `Validate / Build Request` never throws, no
matter what a caller sends as the request body - `null`, an array, a
string, a number, or a genuine JSON object. Anything other than a
non-null JSON object is rejected with a bounded `validationError` (e.g.
`"Request body must be a JSON object."`) that never echoes the raw body
or caller input. `isManual` is preserved on this and every other returned
`json` so the existing production/manual routing is unaffected.

### Webhook authentication: inbound vs. outbound (Correction V3)

The production `Webhook Trigger` requires **Header Auth**
(`authentication: "headerAuth"`) using a dedicated **inbound** credential
(placeholder `__REPLACE_WITH_YOUR_INBOUND_WEBHOOK_CREDENTIAL_ID__`,
display name `FinQuest Live Research Webhook Auth`) - an unauthenticated
caller never reaches `Validate / Build Request`. This is a *separate*
credential from the **outbound** `FinQuest Integration Key` credential
used by `Trigger FinQuest Job`/`Poll Job Status`/`Get Evidence` to
authenticate n8n's own calls *to* FinQuest - see `credentials.example.md`
for how to create both. Neither credential's header name or value is
ever written into this exported JSON, only an id/name placeholder
reference.

### The Webhook's response is an acceptance, not the final result (Correction V3)

`responseMode` on the Webhook Trigger is `responseNode` - a run can poll
for up to ~40 minutes, so the HTTP connection is never held open for the
whole duration:

- **Production, invalid request (pre-`POST`)** - `Respond 400 -
  Validation Error` responds `HTTP 400` with `{"accepted": false,
  "validation_error": "..."}` *before* `Trigger FinQuest Job` ever runs.
  This also covers a missing/invalid FinQuest configuration (see
  "Cloud-reachable configuration" below) - both are bounded, pre-POST
  rejections.
- **Production, valid request, FinQuest accepts it** - `Trigger FinQuest
  Job` creates the `BackgroundJob` first, then `Respond 202 - Accepted`
  immediately responds `HTTP 202` with `{"accepted": true, "job_id":
  "...", "invocation_id": "...", "status": "POLLING_STARTED"}` - **only**
  these four fields, never the research result. The workflow then
  continues to `Init Polling State` and the existing polling loop; its
  eventual outcome (evidence, no-evidence, failure, or timeout) is
  retained only in the n8n execution history, never sent as a second HTTP
  response. No external callback URL is added in this phase.
- **Production, FinQuest rejects or fails the create-job call
  (post-`POST`)** - see "FinQuest 4xx/5xx never crashes the run" below;
  responds `HTTP 400` (rejected) or `HTTP 502` (infrastructure/transport
  failure) and never polls.
- **Manual Trigger (any outcome)** - a `Respond to Webhook` node **never**
  executes on this path, by construction (`Is Manual (Invalid Request)?`
  / `Is Manual (Job Triggered)?` / `Is Manual (Rejected Request)?` / `Is
  Manual (Infra Failure)?` all route around every Respond node entirely) -
  there is no webhook call to respond to. A valid Manual request whose job
  is accepted goes straight to `Init Polling State`; every other manual
  outcome (pre-POST validation failure, a FinQuest rejection, or an
  infrastructure/transport failure) stops at a bounded `noOp` output
  (`Validation Error Output` or `Failure Output`) and never polls.

### FinQuest 4xx/5xx never crashes the run

`Trigger FinQuest Job` sets the HTTP Request node's native "Never Error"
and "Full Response" options (`options.response.response.neverError` /
`.fullResponse`), so a non-2xx response from FinQuest (e.g. a genuine 422
the workflow's own minimal validation did not catch, or a 500) is
returned as normal item data (`statusCode`/`headers`/`body`) instead of
throwing. It also sets `onError: "continueRegularOutput"`, so a true
transport-level failure (DNS, connection refused, timeout - no HTTP
response at all) is likewise converted into a normal item instead of
crashing the execution. `Classify Trigger Response` (immediately
downstream) inspects the result and produces exactly one `outcome`:

- **`ACCEPTED`** - HTTP 2xx with a `job_id` present in the response body.
  Routes to the existing `Is Manual (Job Triggered)?` split (202 / manual
  continuation - see above); polling begins.
- **`REJECTED`** - HTTP 4xx. Never polls. Production responds `HTTP 400`
  via the same `Respond 400 - Validation Error` node used for a pre-POST
  validation failure (via `Build Job Rejected Response`); Manual returns a
  bounded output via the existing `Validation Error Output` noOp (via
  `Build Manual Rejected Output`). Neither ever exposes the complete
  backend response body.
- **`INFRA_FAILURE`** - HTTP 5xx, an unexpected 2xx without a `job_id`, or
  a transport-level failure with no HTTP response at all. Never polls.
  Production responds `HTTP 502` via `Respond 502 - Infra Failure` (via
  `Build Infra Failure Response`); Manual returns a bounded
  `OPERATIONAL_FAILURE` output via the existing `Failure Output` noOp (via
  `Build Manual Infra Failure Output`).

`Trigger Outcome Switch` routes on `outcome`; its `extra` fallback output
(an outcome value other than the three above, impossible by construction)
is defensively wired to the same `InfraFailure` consumer rather than being
silently dropped.

### Cloud-reachable FinQuest configuration, parsed and normalized once

There is **no fallback** to a Docker-internal hostname
(`http://finquest-api:8080`) anywhere in this workflow - unlike the other
workflows in this directory, `live-research-run.json` targets n8n Cloud
and must not assume access to the Docker Compose network.

**`Validate / Build Request` is the only node in the workflow allowed to
read `$vars.FINQUEST_API_BASE_URL` / `$vars.FINQUEST_KEY_ID`** (final
correction). It parses `FINQUEST_API_BASE_URL` with JavaScript's native
`URL` constructor and requires: a string; a hostname (a value with no
authority, e.g. `file:///path`, is rejected); no embedded
username/password (`https://user:pass@host` is rejected); and, for a
production request specifically, the `https:` scheme. The normalized
value has any trailing slash(es) stripped. `FINQUEST_KEY_ID` is required
to be a non-blank string (trimmed). A missing or invalid value of either
stops the workflow right here, before `Trigger FinQuest Job` ever runs,
with the same bounded configuration-error output used for a validation
failure (production: `HTTP 400`).

The validated values are returned as `apiBaseUrl`/`keyId` and carried
forward through the entire workflow's state (`Init Polling State` and
`Merge Polling State` both preserve them). Every FinQuest HTTP Request
node - `Trigger FinQuest Job`, `Poll Job Status`, `Get Evidence` - uses
only `$json.apiBaseUrl`/`$json.keyId`; none of them reads
`$vars.FINQUEST_API_BASE_URL`/`$vars.FINQUEST_KEY_ID` directly. See
`credentials.example.md` section 3a.

### Request contract by scope

| Scope | Required | Forbidden | Required provider(s) |
|---|---|---|---|
| `GENERAL_QUESTION` | `original_question` | any subject, `sec_cik`, `sec_concepts` | Perplexity discovery search |
| `NEWS_SCAN` | `original_question` + exactly one of `subject_security_id`/`subject_raw_text` | `sec_cik`, `sec_concepts` | Perplexity discovery search |
| `ANALYST_SENTIMENT` | `original_question` + exactly one subject | `sec_cik`, `sec_concepts` | Perplexity discovery search |
| `FINANCIAL_FILING_REVIEW` | `original_question` + exactly one subject + `sec_cik` | `sec_concepts` | SEC submissions |
| `COMPANY_OVERVIEW` | `original_question` + exactly one subject + `sec_cik` + non-empty `sec_concepts` | - | SEC company facts **and** Perplexity discovery search |
| `MARKET_DATA_SNAPSHOT` | *(not supported)* | - | - rejected during parameter validation (HTTP 422) before enqueue |

Example production Webhook body (`NEWS_SCAN`):

```json
{
  "invocation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "original_question": "Find recent material news about NVIDIA.",
  "scope": "NEWS_SCAN",
  "subject_raw_text": "NVIDIA Corporation"
}
```

### invocation_id, request-id, and idempotency-key

`invocation_id` is a UUID representing **one logical research
invocation** - generate it once per new logical request and reuse it for
every retry of that same request; a new, independent request (even with
byte-identical parameters) must use a new `invocation_id`. The workflow
derives, and never accepts as separate input:

- `X-FinQuest-Request-ID: livequery-req:<invocation_id>`
- `Idempotency-Key: livequery-idem:<invocation_id>`

Neither identifier is ever derived from question content alone, and the
n8n execution ID is never used as the sole idempotency source.

### Polling and terminal states

Identical polling primitives to every other workflow in this directory,
with Live-Research-specific values: **15-second** interval, and a
**deadline computed once** in `Init Polling State` at approximately **40
minutes** from job creation (`Date.now() + 40 * 60 * 1000`) - a bounded
attempt counter (`maxAttempts`) is kept only as a secondary safety guard,
never the primary timeout signal. Continues polling while status is
`PENDING`/`QUEUED`/`RUNNING`/`RETRY_SCHEDULED`; stops on
`SUCCEEDED`/`FAILED`/`CANCELLED`/`SKIPPED` or once the deadline passes.

`Status Switch` then distinguishes:

- **Completed with evidence** (`SUCCEEDED` + `research_run_status ==
  "COMPLETED"` + `evidence_recorded > 0`): calls the evidence endpoint,
  then `Build Success Summary With Evidence`.
- **Valid no-evidence result** (`SUCCEEDED` + `research_run_status ==
  "FAILED"` + `failure_category == "NO_EVIDENCE_FOUND"`): a **successful**
  workflow outcome with `evidence_recorded: 0` - the evidence endpoint is
  **never** called for this branch.
- **Operational failure** (`FAILED`/`CANCELLED`/`SKIPPED`, or any
  unexpected/malformed `SUCCEEDED` shape): bounded status/error
  information only - the evidence endpoint is never called.
- **Timeout** (the wall-clock deadline is exceeded, **or** the bounded
  `maxAttempts` attempt-counter guard is reached, while still
  non-terminal): a bounded timeout summary preserving
  `job_id`/`invocation_id` for operator follow-up - never creates a
  second job, never calls the evidence endpoint. The `maxAttempts` guard
  is never misclassified as an operational failure.

### The evidence endpoint's 404 vs. 409 contract

`GET /api/v1/integrations/n8n/jobs/{job_id}/live-research/evidence`:

- **404** - the job doesn't exist, belongs to a different
  `IntegrationClient`, or (second authorization layer) its
  `ResearchRequest` belongs to a different `IntegrationClient` than the
  one that owns the `BackgroundJob`. Ownership is always checked first,
  before job type or lifecycle - a non-owner never learns whether the job
  exists, what type it is, or what state it's in.
- **409** - the job exists and is owned by the caller, but is the wrong
  job type, hasn't `SUCCEEDED` yet (including `FAILED`/`CANCELLED`/
  `SKIPPED`), has a missing/malformed `result_summary`, or - even if
  `result_summary` claims `COMPLETED` - the actual `ResearchRun` row in
  PostgreSQL is not `COMPLETED`. Also 409 (job-to-run binding): a missing,
  malformed, or mismatched `result_summary.research_request_id` - it must
  parse as a UUID and equal the loaded `ResearchRun.request_id` exactly,
  even when `research_run_id` itself points at a real, `COMPLETED` run
  owned by the same integration. `result_summary` is never trusted as the
  lifecycle source of truth. Every 409 uses the same bounded, generic
  message (`"Evidence is not available for this job."`) - never a raw
  internal detail.
- **200** - a bounded, provenance-safe `EvidencePageResponse`: only
  `evidence_id`, `source_type`, `classification`, `source_title`,
  `publisher`, `source_url`, `official_identifier`, and `published_at`
  per item, paginated at the database level (`limit`/`offset`, default
  limit 25, maximum 50). Never `raw_excerpt`, `normalized_text`,
  `structured_facts`, provider metadata, or any credential.
  `EvidenceClassification` (`OFFICIAL`/`NON_OFFICIAL`) and `SourceType`
  are exposed literally - discovery evidence is never renamed to imply a
  stronger provenance guarantee than it actually has.

### IntegrationClient permission management (grant/revoke)

See `credentials.example.md` for the exact CLI commands to create a
dedicated canary client, grant/revoke the `LIVE_RESEARCH_RUN_EXECUTION`
permission on an existing client, and the production canary sequence.

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

`live-research-run.json` additionally has its own dedicated
`TestLiveResearchRunWorkflow` class (same file) verifying its
production-vs-dev-only trigger split, the mandatory `invocation_id`
gate (including canonical-UUID validation), the 15-second/40-minute
polling contract, that the `maxAttempts` guard routes to the Timeout
branch (never `OPERATIONAL_FAILURE`), that the first poll iteration
never dereferences the not-yet-executed `Increment Poll Attempt` node,
that no Node built-in module is required anywhere in the file, and that
the completed-with-evidence branch is the *only* branch that calls the
evidence endpoint.

**Correction V3** added: the Webhook requires Header Auth via a distinct
inbound credential placeholder (never equal to the outbound one, and no
credential value anywhere in the JSON); `responseMode` is `responseNode`
with `Respond 400 - Validation Error`/`Respond 202 - Accepted` correctly
wired for all four manual/production × valid/invalid paths (a `Respond to
Webhook` node is asserted to never be reachable from a Manual Trigger
run); no Docker-internal fallback hostname remains; and a missing
`FINQUEST_API_BASE_URL`/`FINQUEST_KEY_ID` is asserted to block
`Trigger FinQuest Job`.

**Final correction** added: every FinQuest HTTP node is asserted to use
`$json.apiBaseUrl`/`$json.keyId` rather than reading
`$vars.FINQUEST_API_BASE_URL`/`$vars.FINQUEST_KEY_ID` directly, and that
only `Validate / Build Request` ever reads those two variables; a third
`Respond to Webhook` node (`Respond 502 - Infra Failure`) exists alongside
202/400; `Trigger FinQuest Job` is asserted to set the "Never Error"/"Full
Response" options and `onError: continueRegularOutput`; and a graph
reachability check proves neither the `Rejected` nor the `InfraFailure`
outcome of `Classify Trigger Response` can ever reach `Init Polling
State`/`Wait Before Poll`/`Trigger FinQuest Job` (i.e. a rejected or
failed job-creation attempt is never polled and never retried
automatically). Two dedicated Node.js-execution test classes (both
skipped automatically when a local Node.js binary is unavailable) prove
runtime behavior rather than only pattern-matching source text:

- `TestValidateBuildRequestExecution` executes `Validate / Build
  Request`'s `jsCode` against a minimal `$input`/`$execution`/`$vars`
  shim - proving the safe input envelope (`null`/array/string/number
  bodies all return a bounded `validationError` and never throw), the
  minimal per-scope/per-field validation (whitespace-only
  `subject_raw_text` becomes absent, a non-string/blank
  `original_question` is rejected, valid input is normalized and reaches
  the point of building the FinQuest job payload), and the
  `FINQUEST_API_BASE_URL`/`FINQUEST_KEY_ID` parsing/normalization gate
  (malformed URL, no hostname, embedded credentials, non-HTTPS on the
  production path, and whitespace-surrounded values on both are all
  handled correctly, returning `apiBaseUrl`/`keyId` on success).
- `TestClassifyTriggerResponseExecution` executes `Classify Trigger
  Response`'s `jsCode` against a minimal `$input`/`$()` shim - proving a
  successful create-job response (2xx with a `job_id`, nested or flat)
  reaches `ACCEPTED`, a simulated HTTP 422 reaches `REJECTED`, a simulated
  HTTP 500 or a transport failure with no `statusCode` at all reaches
  `INFRA_FAILURE`, and a 2xx response missing a `job_id` is still treated
  as `INFRA_FAILURE` rather than incorrectly `ACCEPTED`.
