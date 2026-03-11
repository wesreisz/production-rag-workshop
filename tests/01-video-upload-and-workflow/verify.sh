#!/usr/bin/env bash
set -euo pipefail

TF_DIR="$(cd "$(dirname "$0")/../../infra/environments/dev" && pwd)"

BUCKET=$(terraform -chdir="$TF_DIR" output -raw media_bucket_name)
STATE_MACHINE=$(terraform -chdir="$TF_DIR" output -raw state_machine_arn)

SAMPLE_FILE="$(cd "$(dirname "$0")/../../samples" && pwd)/hello-my_name_is_wes.mp3"

echo "=== 1. Upload sample audio ==="
aws s3 cp "$SAMPLE_FILE" "s3://${BUCKET}/uploads/hello-my_name_is_wes.mp3" \
  --metadata '{"speaker":"Wesley Reisz","title":"Hello, my name is Wes"}'
echo "Uploaded to s3://${BUCKET}/uploads/hello-my_name_is_wes.mp3"

echo ""
echo "=== 2. Wait for EventBridge to trigger execution ==="
sleep 5

EXECUTION_ARN=$(aws stepfunctions list-executions \
  --state-machine-arn "$STATE_MACHINE" \
  --max-results 1 \
  --query 'executions[0].executionArn' \
  --output text)

echo ""
echo "=== 3. Verify execution was triggered ==="
if [ -z "$EXECUTION_ARN" ] || [ "$EXECUTION_ARN" = "None" ]; then
  echo "FAIL — no execution found"
  exit 1
fi

echo "Found execution: $EXECUTION_ARN"

STATUS=$(aws stepfunctions describe-execution \
  --execution-arn "$EXECUTION_ARN" \
  --query 'status' \
  --output text)

echo "Status: $STATUS"
echo "PASS — S3 upload triggered Step Functions execution"

echo ""
echo "=== 4. Execution input ==="
aws stepfunctions describe-execution \
  --execution-arn "$EXECUTION_ARN" \
  --query 'input' \
  --output text | python3 -m json.tool
