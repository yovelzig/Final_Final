# n8n credential setup (example - no real values)

FinQuest's n8n integration authenticates with two headers:

```text
X-FinQuest-Key-Id:         a public key identifier (not secret)
X-FinQuest-Integration-Key: the raw API key (secret - shown once at creation time)
```

Neither is a learner JWT. Never paste a real API key into a workflow's
JSON export - it belongs only in n8n's own encrypted credential store.

## 1. Generate an integration client

On the FinQuest API host (or any machine with the `stock-research-core`
package and database access):

```powershell
python -m stock_research_core.cli.operations_admin `
  --create-integration-client `
  --name "FinQuest n8n" `
  --allow-job TRACKED_MARKET_REFRESH `
  --allow-job PORTFOLIO_BATCH_VALUATION `
  --allow-job CURRICULUM_KNOWLEDGE_REFRESH `
  --allow-job RETRIEVAL_EVALUATION
```

This prints the raw API key **exactly once**. Copy it immediately - it
is never stored or shown again (only its SHA-256 hash is kept).

## 2. Create the n8n credential

In n8n: **Credentials → New → Header Auth** (generic `httpHeaderAuth`
credential type, built into n8n - no custom credential type needed).

| Field | Example value |
|---|---|
| Credential name | `FinQuest Integration Key` |
| Header Name | `X-FinQuest-Integration-Key` |
| Header Value | *(paste the raw API key from step 1)* |

This is the **outbound** credential - it authenticates n8n's own calls
*to* the FinQuest API (`Trigger FinQuest Job`, `Poll Job Status`,
`Get Evidence` in `live-research-run.json`, and the equivalent HTTP
Request nodes in every other workflow in this directory).

### 2a. Live Research only: the inbound webhook credential (Correction V3)

`live-research-run.json`'s production `Webhook Trigger` is a *second*,
independent credential in the opposite direction - it authenticates an
**inbound** caller calling *into* n8n, and is never used for n8n's own
outbound calls above.

In n8n: **Credentials → New → Header Auth** (same generic `httpHeaderAuth`
type, a second, separate credential entry).

| Field | Example value |
|---|---|
| Credential name | `FinQuest Live Research Webhook Auth` |
| Header Name | *(your choice, e.g. `X-Inbound-Webhook-Key`)* |
| Header Value | *(a secret you generate and give only to the authorized caller)* |

Then, on the imported `Webhook Trigger` node: set **Authentication** to
**Header Auth** and map its credential to `FinQuest Live Research Webhook
Auth`. The exported `live-research-run.json` never contains this header's
name or value - only a `__REPLACE_WITH_YOUR_INBOUND_WEBHOOK_CREDENTIAL_ID__`
placeholder that n8n prompts you to map at import time, exactly like the
outbound credential.

**Inbound vs. outbound, at a glance:**

| | Direction | Credential name | Used by |
|---|---|---|---|
| Outbound | n8n → FinQuest API | `FinQuest Integration Key` | `Trigger FinQuest Job`, `Poll Job Status`, `Get Evidence` (all workflows) |
| Inbound | caller → n8n Webhook | `FinQuest Live Research Webhook Auth` | `Webhook Trigger` (`live-research-run.json` only) |

These are two different secrets in two different credential entries -
never reuse one value for both.

## 3. Set n8n environment variables (or Workflow Static Data / `$vars`)

| Variable | Example value |
|---|---|
| `FINQUEST_API_BASE_URL` | `http://finquest-api:8080` (inside the Docker network) or `https://api.finquest.example.com` |
| `FINQUEST_KEY_ID` | the `key_id` printed alongside the raw API key in step 1 (not secret) |
| `FINQUEST_MARKET_MAX_CONCURRENCY` | `4` |
| `FINQUEST_PORTFOLIO_MAX_CONCURRENCY` | `4` |
| `FINQUEST_EVAL_DATASET` | `default_v1` |
| `FINQUEST_EVAL_TOP_K` | `5` |

Every workflow JSON in `n8n/workflows/` references these as
`$vars.FINQUEST_*` expressions and the `FinQuest Integration Key`
credential by name - importing a workflow will prompt you to map its
credential placeholder to the one you created in step 2.

### 3a. Live Research only: `FINQUEST_API_BASE_URL` must be HTTPS, parsed once (final correction)

`live-research-run.json` targets n8n **Cloud**, not a self-hosted n8n on
the same Docker network as `finquest-api` - unlike the other workflows in
this directory, it has **no fallback** to `http://finquest-api:8080` at
all. `Validate / Build Request` is the **only** node in the workflow
allowed to read `$vars.FINQUEST_API_BASE_URL` / `$vars.FINQUEST_KEY_ID` -
every FinQuest HTTP Request node (`Trigger FinQuest Job`, `Poll Job
Status`, `Get Evidence`) instead uses the already-validated
`$json.apiBaseUrl` / `$json.keyId` carried through the workflow's state.

`FINQUEST_API_BASE_URL` is parsed with JavaScript's native `URL`
constructor and must have: a hostname (a schema-only value with no
authority, e.g. `file:///path`, is rejected); no embedded
username/password (`https://user:pass@host` is rejected); and, for the
production Webhook path specifically, the `https:` scheme (e.g.
`https://api.finquest.example.com`) - a plain `http://` value is rejected
for a production request. Any surrounding whitespace and any trailing
slash(es) are stripped automatically. `FINQUEST_KEY_ID` must be a
non-blank string (also trimmed). A missing or invalid value of either
stops the workflow before `Trigger FinQuest Job` with a bounded
configuration-error output - production responds `HTTP 400`. The Manual
Trigger (dev/testing) path tolerates a non-HTTPS value (e.g.
`http://localhost:8080`) for local testing, but still requires both
variables to be set and well-formed.

## 4. Import the workflows

**n8n UI → Workflows → Import from File**, one at a time, from
`n8n/workflows/*.json`. After import, open each workflow, confirm the
HTTP Request nodes' credential is mapped to `FinQuest Integration Key`,
and activate it.

## What n8n never receives

- A database URL or Redis URL.
- Raw password/JWT/refresh-token material.
- Direct database access - every workflow calls the FinQuest API only.
- A Perplexity API key or a SEC EDGAR `User-Agent` - n8n never calls
  either provider directly (see "Live Research (Phase G2C)" below).

## What the exported workflow JSON never contains

Neither the outbound (`FinQuest Integration Key`) nor the inbound
(`FinQuest Live Research Webhook Auth`) credential's header name or value
is ever written into a workflow's exported JSON - only a
`__REPLACE_WITH_...` credential-id placeholder that n8n resolves against
its own encrypted credential store at import time. Committing an exported
workflow to source control (as this repository does under
`n8n/workflows/`) never leaks either secret.

## Live Research (Phase G2C): IntegrationClient job-permission management

`live-research-run.json` needs an `IntegrationClient` whose
`allowed_job_types` includes `LIVE_RESEARCH_RUN_EXECUTION`. This is a
*fourth*, independent activation gate on top of the job registry
allowing `N8N`, `LIVE_RESEARCH_JOBS_ENABLED=true`, and the selected
scope's required provider flag(s) being enabled - see
`docs/migration-status.md`'s "Phase G2C" section for the full gate list.

### The Webhook's response is an acceptance, not the final result (Correction V3; 400/502 split in the final correction)

A caller `POST`ing to the production Webhook does not wait ~40 minutes
for the research result. The Webhook responds immediately:

- **`HTTP 400`** - either the request (or the FinQuest configuration)
  failed n8n's own minimal pre-POST validation, so `Trigger FinQuest Job`
  never ran; or FinQuest itself rejected the create-job call with a 4xx
  (e.g. a backend validation failure n8n's own minimal check did not
  catch). Body in both cases: `{"accepted": false, "validation_error":
  "..."}` - the complete FinQuest response body is never exposed.
- **`HTTP 202`** - the `BackgroundJob` was created. Body: `{"accepted":
  true, "job_id": "...", "invocation_id": "...", "status":
  "POLLING_STARTED"}` - **only** these four fields, never the research
  result itself.
- **`HTTP 502`** - FinQuest returned a 5xx, or the create-job call failed
  at the transport level (DNS, connection refused, timeout). Never polls.
  Body: `{"accepted": false, "operational_error": "..."}` - never the raw
  transport error or a traceback.

After the `202`, the workflow keeps running inside n8n (polling every 15
seconds for up to ~40 minutes) and its final bounded outcome - evidence,
no-evidence, an operational failure, or a timeout - is retained only in
that execution's history. Look it up in the n8n UI, or poll
`GET /api/v1/integrations/n8n/jobs/{job_id}` directly with the same
outbound credential. This phase does not add an external callback URL.

### New dedicated canary/production client

```powershell
python -m stock_research_core.cli.operations_admin `
  --create-integration-client `
  --name "FinQuest Live Research Canary" `
  --allow-job LIVE_RESEARCH_RUN_EXECUTION
```

The permission is already present after creation - **do not** also call
`--grant-integration-job-type` for the same permission immediately
afterward (it would be a harmless no-op, but is unnecessary).

### Granting the permission to an existing client

```powershell
python -m stock_research_core.cli.operations_admin `
  --grant-integration-job-type <INTEGRATION_UUID> `
  --job-type LIVE_RESEARCH_RUN_EXECUTION
```

Adds the permission without rotating or revealing the client's API key,
and without touching any of its other allowed job types. Idempotent -
granting an already-granted permission is a no-op.

### Revoking the permission (rollback)

```powershell
python -m stock_research_core.cli.operations_admin `
  --revoke-integration-job-type <INTEGRATION_UUID> `
  --job-type LIVE_RESEARCH_RUN_EXECUTION
```

Idempotent - revoking an already-absent permission is a no-op. **An
`ACTIVE` client can never be revoked down to zero allowed job types** -
grant a replacement job type first, or disable the client
(`--revoke-integration-client`, which fully revokes the client itself)
instead. Both commands call `IntegrationClientAdminService` under a
single row-locked transaction and never print the client's
`api_key_hash` or any provider credential.

### Production canary sequence (documented here; not performed by any automated process)

1. **SEC only:** `LIVE_RESEARCH_JOBS_ENABLED=true`,
   `LIVE_RESEARCH_SEC_ENABLED=true`,
   `LIVE_RESEARCH_PERPLEXITY_ENABLED=false`; trigger
   `FINANCIAL_FILING_REVIEW`; confirm the returned evidence is
   `SEC_OFFICIAL_FILING` + `OFFICIAL`.
2. **Perplexity only:** `LIVE_RESEARCH_SEC_ENABLED=false`,
   `LIVE_RESEARCH_PERPLEXITY_ENABLED=true`; trigger `GENERAL_QUESTION` or
   `NEWS_SCAN`; confirm `DISCOVERY_ONLY` + `NON_OFFICIAL`.
3. **Both providers:** trigger `COMPANY_OVERVIEW`; confirm both provider
   paths ran and official/non-official evidence remain visibly
   distinguishable.
4. **Rollback:** `--revoke-integration-job-type` for the canary client;
   remove `N8N` from `job_registry.py`'s `LIVE_RESEARCH_RUN_EXECUTION`
   entry in a separate, reviewed rollback release if the trigger source
   itself must be disabled; set the job/provider flags back to `false`.
