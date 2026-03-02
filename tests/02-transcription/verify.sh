#!/usr/bin/env bash
set -euo pipefail

MODULE_DIR="$(cd "$(dirname "$0")/../../modules/transcribe-module" && pwd)"
TF_DIR="$(cd "$(dirname "$0")/../../infra/environments/dev" && pwd)"
SAMPLES_DIR="$(cd "$(dirname "$0")/../../samples" && pwd)"

echo "=== 0. Unit test reminder ==="
echo "Run unit tests separately:"
echo "  cd $MODULE_DIR && source .venv/bin/activate && python -m pytest tests/ -v"
echo ""

BUCKET=$(terraform -chdir="$TF_DIR" output -raw media_bucket_name)
STATE_MACHINE=$(terraform -chdir="$TF_DIR" output -raw state_machine_arn)

EXISTING=$(aws s3 ls "s3://${BUCKET}/uploads/test-hello-" --recursive 2>/dev/null | wc -l | tr -d ' ')
RUN_NUM=$(printf "%03d" $((EXISTING + 1)))
UPLOAD_NAME="test-hello-${RUN_NUM}.mp3"
VIDEO_ID="test-hello-${RUN_NUM}"

echo "=== 1. Upload sample audio (run ${RUN_NUM}) ==="
aws s3 cp "$SAMPLES_DIR/hello-my_name_is_wes.mp3" "s3://${BUCKET}/uploads/${UPLOAD_NAME}"
echo "Uploaded to s3://${BUCKET}/uploads/${UPLOAD_NAME}"

echo ""
echo "=== 2. Wait for execution to start (15s) ==="
sleep 15

EXECUTION_ARN=$(aws stepfunctions list-executions \
  --state-machine-arn "$STATE_MACHINE" \
  --max-results 1 \
  --query 'executions[0].executionArn' \
  --output text)

echo "Execution: $EXECUTION_ARN"

echo ""
echo "=== 3. Poll for completion (up to 5 min) ==="
MAX_WAIT=300
ELAPSED=0
INTERVAL=15

while [ $ELAPSED -lt $MAX_WAIT ]; do
  STATUS=$(aws stepfunctions describe-execution \
    --execution-arn "$EXECUTION_ARN" \
    --query 'status' \
    --output text)

  echo "  [${ELAPSED}s] Status: $STATUS"

  if [ "$STATUS" = "SUCCEEDED" ] || [ "$STATUS" = "FAILED" ] || [ "$STATUS" = "TIMED_OUT" ] || [ "$STATUS" = "ABORTED" ]; then
    break
  fi

  sleep $INTERVAL
  ELAPSED=$((ELAPSED + INTERVAL))
done

echo ""
echo "=== 4. Verify execution result ==="
if [ "$STATUS" = "SUCCEEDED" ]; then
  echo "PASS — execution succeeded"
else
  echo "FAIL — expected SUCCEEDED, got $STATUS"
  exit 1
fi

echo ""
echo "=== 5. Verify transcript in S3 ==="
TRANSCRIPT_KEY="transcripts/${VIDEO_ID}/raw.json"

if aws s3 ls "s3://${BUCKET}/${TRANSCRIPT_KEY}" > /dev/null 2>&1; then
  echo "PASS — transcript exists at s3://${BUCKET}/${TRANSCRIPT_KEY}"
else
  echo "FAIL — transcript not found at s3://${BUCKET}/${TRANSCRIPT_KEY}"
  exit 1
fi

echo ""
echo "=== 6. Verify transcript content ==="
aws s3 cp "s3://${BUCKET}/${TRANSCRIPT_KEY}" /tmp/transcript.json --quiet

TRANSCRIPT_TEXT=$(python3 -c "
import json
t = json.load(open('/tmp/transcript.json'))
text = t['results']['transcripts'][0]['transcript']
print(text[:200])
")

if [ -n "$TRANSCRIPT_TEXT" ]; then
  echo "PASS — transcript has content:"
  echo "  $TRANSCRIPT_TEXT"
else
  echo "FAIL — transcript text is empty"
  exit 1
fi

echo ""
echo "=== 7. Verify wait/poll loop executed ==="
WAIT_COUNT=$(aws stepfunctions get-execution-history \
  --execution-arn "$EXECUTION_ARN" \
  --query "length(events[?type=='WaitStateExited'])" \
  --output text)

echo "Wait loop iterations: $WAIT_COUNT"

if [ "$WAIT_COUNT" -ge 1 ]; then
  echo "PASS — poll loop executed"
else
  echo "FAIL — no wait states observed"
  exit 1
fi

echo ""
echo "=== All checks passed ==="
