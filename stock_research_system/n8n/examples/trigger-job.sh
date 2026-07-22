#!/usr/bin/env bash
# Manually trigger a FinQuest background job through the n8n integration
# API - the same contract n8n itself uses. Useful for testing without a
# running n8n instance.
#
# Usage:
#   export FINQUEST_KEY_ID=...
#   export FINQUEST_INTEGRATION_KEY=...
#   ./trigger-job.sh RETRIEVAL_EVALUATION '{"evaluation_dataset":"default_v1","top_k":5}'
#
# The API key is read from an environment variable only - never pass it
# as a script argument (it would land in shell history).
set -euo pipefail

JOB_TYPE="${1:?usage: trigger-job.sh JOB_TYPE [PARAMETERS_JSON] [API_BASE_URL]}"
PARAMETERS="${2:-{}}"
API_BASE_URL="${3:-http://localhost:8080}"

if [ -z "${FINQUEST_KEY_ID:-}" ] || [ -z "${FINQUEST_INTEGRATION_KEY:-}" ]; then
  echo "Set FINQUEST_KEY_ID and FINQUEST_INTEGRATION_KEY environment variables first." >&2
  exit 1
fi

EXTERNAL_REQUEST_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
IDEMPOTENCY_KEY="${JOB_TYPE}-manual-$(date -u +%Y-%m-%dT%H)"

BODY="$(python3 -c "import json,sys; print(json.dumps({'job_type': sys.argv[1], 'parameters': json.loads(sys.argv[2])}))" "$JOB_TYPE" "$PARAMETERS")"

RESPONSE="$(curl -sS -X POST "$API_BASE_URL/api/v1/integrations/n8n/jobs" \
  -H "X-FinQuest-Key-Id: $FINQUEST_KEY_ID" \
  -H "X-FinQuest-Integration-Key: $FINQUEST_INTEGRATION_KEY" \
  -H "X-FinQuest-Request-ID: $EXTERNAL_REQUEST_ID" \
  -H "Idempotency-Key: $IDEMPOTENCY_KEY" \
  -H "Content-Type: application/json" \
  -d "$BODY")"

JOB_ID="$(python3 -c "import json,sys; print(json.load(sys.stdin)['job']['job_id'])" <<< "$RESPONSE")"
echo "Created job: $JOB_ID"

for _ in $(seq 1 40); do
  sleep 15
  POLL="$(curl -sS "$API_BASE_URL/api/v1/integrations/n8n/jobs/$JOB_ID" \
    -H "X-FinQuest-Key-Id: $FINQUEST_KEY_ID" \
    -H "X-FinQuest-Integration-Key: $FINQUEST_INTEGRATION_KEY")"
  STATUS="$(python3 -c "import json,sys; print(json.load(sys.stdin)['status'])" <<< "$POLL")"
  echo "  status: $STATUS"
  case "$STATUS" in
    SUCCEEDED|FAILED|CANCELLED|SKIPPED)
      echo "Final status: $STATUS"
      echo "$POLL" | python3 -m json.tool
      exit 0
      ;;
  esac
done

echo "Polling timed out after 40 attempts." >&2
exit 1
