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

## 4. Import the workflows

**n8n UI → Workflows → Import from File**, one at a time, from
`n8n/workflows/*.json`. After import, open each workflow, confirm the
HTTP Request nodes' credential is mapped to `FinQuest Integration Key`,
and activate it.

## What n8n never receives

- A database URL or Redis URL.
- Raw password/JWT/refresh-token material.
- Direct database access - every workflow calls the FinQuest API only.
