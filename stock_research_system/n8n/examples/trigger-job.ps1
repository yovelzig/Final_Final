# Manually trigger a FinQuest background job through the n8n integration
# API - the same contract n8n itself uses. Useful for testing without a
# running n8n instance.
#
# Usage:
#   $env:FINQUEST_KEY_ID = "..."
#   $env:FINQUEST_INTEGRATION_KEY = "..."
#   .\trigger-job.ps1 -JobType RETRIEVAL_EVALUATION -Parameters '{"evaluation_dataset":"default_v1","top_k":5}'
#
# The API key is read from an environment variable only - never pass it
# as a script argument (it would land in shell history).

param(
    [Parameter(Mandatory = $true)][string]$JobType,
    [string]$Parameters = "{}",
    [string]$ApiBaseUrl = "http://localhost:8080"
)

if (-not $env:FINQUEST_KEY_ID -or -not $env:FINQUEST_INTEGRATION_KEY) {
    Write-Error "Set FINQUEST_KEY_ID and FINQUEST_INTEGRATION_KEY environment variables first."
    exit 1
}

$externalRequestId = [guid]::NewGuid().ToString()
$idempotencyKey = "$JobType-manual-$(Get-Date -Format 'yyyy-MM-ddTHH')"

$headers = @{
    "X-FinQuest-Key-Id"          = $env:FINQUEST_KEY_ID
    "X-FinQuest-Integration-Key" = $env:FINQUEST_INTEGRATION_KEY
    "X-FinQuest-Request-ID"      = $externalRequestId
    "Idempotency-Key"            = $idempotencyKey
    "Content-Type"               = "application/json"
}

$body = @{
    job_type   = $JobType
    parameters = ($Parameters | ConvertFrom-Json)
} | ConvertTo-Json -Depth 10

$response = Invoke-RestMethod -Method Post -Uri "$ApiBaseUrl/api/v1/integrations/n8n/jobs" -Headers $headers -Body $body
Write-Output "Created job: $($response.job.job_id) status=$($response.job.status)"

$jobId = $response.job.job_id
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    Start-Sleep -Seconds 15
    $poll = Invoke-RestMethod -Method Get -Uri "$ApiBaseUrl/api/v1/integrations/n8n/jobs/$jobId" -Headers @{ "X-FinQuest-Key-Id" = $env:FINQUEST_KEY_ID; "X-FinQuest-Integration-Key" = $env:FINQUEST_INTEGRATION_KEY }
    Write-Output "  status: $($poll.status)"
    if ($poll.status -in @("SUCCEEDED", "FAILED", "CANCELLED", "SKIPPED")) {
        Write-Output "Final status: $($poll.status)"
        Write-Output ($poll.result_summary | ConvertTo-Json -Depth 10)
        exit 0
    }
}
Write-Warning "Polling timed out after 40 attempts."
exit 1
