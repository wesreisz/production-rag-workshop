#!/usr/bin/env bash
set -euo pipefail

TF_DIR="$(cd "$(dirname "$0")/../../infra/environments/dev" && pwd)"

BUCKET=$(terraform -chdir="$TF_DIR" output -raw media_bucket_name)
STATE_MACHINE=$(terraform -chdir="$TF_DIR" output -raw state_machine_arn)

echo "=== 1. Upload test file ==="
echo "test-$(date +%s)" > /tmp/test-upload.txt
aws s3 cp /tmp/test-upload.txt "s3://${BUCKET}/uploads/test-upload.txt"
echo "Uploaded to s3://${BUCKET}/uploads/test-upload.txt"

echo ""
echo "=== 2. Wait for execution (15s) ==="
sleep 15

echo ""
echo "=== 3. Check latest execution ==="
STATUS=$(aws stepfunctions list-executions \
  --state-machine-arn "$STATE_MACHINE" \
  --max-results 1 \
  --query 'executions[0].status' \
  --output text)

echo "Status: $STATUS"

if [ "$STATUS" = "SUCCEEDED" ]; then
  echo "PASS"
else
  echo "FAIL — expected SUCCEEDED, got $STATUS"
  exit 1
fi

echo ""
echo "=== 4. Execution input ==="
EXECUTION_ARN=$(aws stepfunctions list-executions \
  --state-machine-arn "$STATE_MACHINE" \
  --max-results 1 \
  --query 'executions[0].executionArn' \
  --output text)

aws stepfunctions describe-execution \
  --execution-arn "$EXECUTION_ARN" \
  --query 'input' \
  --output text | python3 -m json.tool
