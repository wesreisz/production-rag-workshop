#!/usr/bin/env bash
set -euo pipefail

MODULE_DIR="$(cd "$(dirname "$0")/../../modules/embedding-module" && pwd)"
TF_DIR="$(cd "$(dirname "$0")/../../infra/environments/dev" && pwd)"
SAMPLES_DIR="$(cd "$(dirname "$0")/../../samples" && pwd)"
PASS_COUNT=0
FAIL_COUNT=0

pass() { echo "  PASS — $1"; PASS_COUNT=$((PASS_COUNT + 1)); }
fail() { echo "  FAIL — $1"; FAIL_COUNT=$((FAIL_COUNT + 1)); }

echo "=== 0. Unit tests ==="
echo "Run unit tests separately:"
echo "  cd $MODULE_DIR && python -m pytest tests/ -v"
echo ""

read -rp "Press Enter to continue with AWS verification or Ctrl+C to exit... "

echo ""
echo "=== 1. Embedding module code exists ==="
if [ -f "$MODULE_DIR/src/handlers/process_embedding.py" ] && [ -f "$MODULE_DIR/src/services/embedding_service.py" ]; then
  pass "handlers and services directories have Python files"
else
  fail "embedding module source files missing"
fi

echo ""
echo "=== 2. Embedding Lambda deployed ==="
FUNC_NAME=$(terraform -chdir="$TF_DIR" output -raw embedding_function_name 2>/dev/null || echo "")
if [ -z "$FUNC_NAME" ]; then
  fail "embedding_function_name output not found — has terraform apply been run?"
  echo ""
  echo "========================================="
  echo "  Results: $PASS_COUNT passed, $FAIL_COUNT failed"
  echo "========================================="
  exit 1
fi

FUNC_EXISTS=$(aws lambda get-function --function-name "$FUNC_NAME" --query 'Configuration.FunctionName' --output text 2>/dev/null || echo "None")
if [ "$FUNC_EXISTS" = "$FUNC_NAME" ]; then
  pass "Lambda function exists ($FUNC_NAME)"
else
  fail "Lambda function $FUNC_NAME not found"
fi

echo ""
echo "=== 3. Lambda is VPC-attached ==="
VPC_SUBNETS=$(aws lambda get-function-configuration \
  --function-name "$FUNC_NAME" \
  --query 'VpcConfig.SubnetIds' --output text 2>/dev/null || echo "None")
VPC_SGS=$(aws lambda get-function-configuration \
  --function-name "$FUNC_NAME" \
  --query 'VpcConfig.SecurityGroupIds' --output text 2>/dev/null || echo "None")

if [ "$VPC_SUBNETS" != "None" ] && [ -n "$VPC_SUBNETS" ]; then
  pass "Lambda has VPC subnets configured"
else
  fail "Lambda VPC subnets not configured"
fi

if [ "$VPC_SGS" != "None" ] && [ -n "$VPC_SGS" ]; then
  pass "Lambda has security groups configured"
else
  fail "Lambda security groups not configured"
fi

echo ""
echo "=== 4. Lambda has psycopg2 layer ==="
LAYER_COUNT=$(aws lambda get-function-configuration \
  --function-name "$FUNC_NAME" \
  --query 'length(Layers)' --output text 2>/dev/null || echo "0")
LAYER_ARN=$(aws lambda get-function-configuration \
  --function-name "$FUNC_NAME" \
  --query 'Layers[0].Arn' --output text 2>/dev/null || echo "None")

if [ "$LAYER_COUNT" -ge 1 ] && echo "$LAYER_ARN" | grep -q "psycopg2"; then
  pass "psycopg2 layer attached ($LAYER_ARN)"
else
  fail "psycopg2 layer not found on function (layers: $LAYER_COUNT)"
fi

echo ""
echo "=== 5. SQS event source mapping ==="
ESM_UUID=$(aws lambda list-event-source-mappings \
  --function-name "$FUNC_NAME" \
  --query 'EventSourceMappings[0].UUID' --output text 2>/dev/null || echo "None")
ESM_BATCH=$(aws lambda list-event-source-mappings \
  --function-name "$FUNC_NAME" \
  --query 'EventSourceMappings[0].BatchSize' --output text 2>/dev/null || echo "0")

if [ "$ESM_UUID" != "None" ] && [ -n "$ESM_UUID" ]; then
  pass "Event source mapping exists ($ESM_UUID)"
else
  fail "No event source mapping found"
fi

if [ "$ESM_BATCH" = "1" ]; then
  pass "Batch size is 1"
else
  fail "Batch size is $ESM_BATCH, expected 1"
fi

echo ""
echo "=== 6. Trigger pipeline (upload sample audio) ==="
BUCKET=$(terraform -chdir="$TF_DIR" output -raw media_bucket_name)
STATE_MACHINE=$(terraform -chdir="$TF_DIR" output -raw state_machine_arn)

EXISTING=$( (aws s3 ls "s3://${BUCKET}/uploads/test-embed-" --recursive 2>/dev/null || true) | wc -l | tr -d ' ')
RUN_NUM=$(printf "%03d" $((EXISTING + 1)))
UPLOAD_NAME="test-embed-${RUN_NUM}.mp3"
VIDEO_ID="test-embed-${RUN_NUM}"

aws s3 cp "$SAMPLES_DIR/hello-my_name_is_wes.mp3" "s3://${BUCKET}/uploads/${UPLOAD_NAME}" \
  --metadata '{"speaker":"Wesley Reisz","title":"Hello, my name is Wes"}'
echo "  Uploaded to s3://${BUCKET}/uploads/${UPLOAD_NAME}"

echo ""
echo "=== 7. Wait for Step Functions execution (up to 5 min) ==="
sleep 15
EXECUTION_ARN=$(aws stepfunctions list-executions \
  --state-machine-arn "$STATE_MACHINE" \
  --max-results 1 \
  --query 'executions[0].executionArn' \
  --output text)
echo "  Execution: $EXECUTION_ARN"

MAX_WAIT=300
ELAPSED=0
INTERVAL=15
STATUS="RUNNING"

while [ $ELAPSED -lt $MAX_WAIT ]; do
  STATUS=$(aws stepfunctions describe-execution \
    --execution-arn "$EXECUTION_ARN" \
    --query 'status' --output text)
  echo "  [${ELAPSED}s] Status: $STATUS"
  if [ "$STATUS" = "SUCCEEDED" ] || [ "$STATUS" = "FAILED" ] || [ "$STATUS" = "TIMED_OUT" ] || [ "$STATUS" = "ABORTED" ]; then
    break
  fi
  sleep $INTERVAL
  ELAPSED=$((ELAPSED + INTERVAL))
done

if [ "$STATUS" = "SUCCEEDED" ]; then
  pass "Step Functions execution succeeded"
else
  fail "Step Functions execution status: $STATUS"
fi

echo ""
echo "=== 8. Wait for embedding Lambda to process (60s) ==="
sleep 60

echo ""
echo "=== 9. Verify SQS queue is drained ==="
QUEUE_URL=$(terraform -chdir="$TF_DIR" output -raw embedding_queue_url)
SQS_VISIBLE=$(aws sqs get-queue-attributes \
  --queue-url "$QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages \
  --query "Attributes.ApproximateNumberOfMessages" --output text)
SQS_INFLIGHT=$(aws sqs get-queue-attributes \
  --queue-url "$QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessagesNotVisible \
  --query "Attributes.ApproximateNumberOfMessagesNotVisible" --output text)

if [ "$SQS_VISIBLE" = "0" ] && [ "$SQS_INFLIGHT" = "0" ]; then
  pass "Embedding queue drained (visible=$SQS_VISIBLE, inflight=$SQS_INFLIGHT)"
else
  fail "Embedding queue not empty (visible=$SQS_VISIBLE, inflight=$SQS_INFLIGHT)"
fi

echo ""
echo "=== 10. Verify DLQ is empty ==="
DLQ_URL=$(aws sqs get-queue-url --queue-name production-rag-embedding-dlq --query 'QueueUrl' --output text 2>/dev/null || echo "")
if [ -n "$DLQ_URL" ]; then
  DLQ_COUNT=$(aws sqs get-queue-attributes \
    --queue-url "$DLQ_URL" \
    --attribute-names ApproximateNumberOfMessages \
    --query "Attributes.ApproximateNumberOfMessages" --output text)
  if [ "$DLQ_COUNT" = "0" ]; then
    pass "DLQ is empty"
  else
    fail "DLQ has $DLQ_COUNT message(s)"
  fi
else
  fail "DLQ not found"
fi

echo ""
echo "=== 11. Verify embeddings in pgvector ==="
echo ""
echo "  Use EITHER Option A (RDS Query Editor) or Option B (CloudShell VPC):"
echo ""
echo "  ── Option A: RDS Query Editor (recommended) ──"
echo "  1. Open the AWS Console > RDS > Query Editor"
echo "  2. Connect with:"
echo "     - Database instance: production-rag-vectordb"
echo "     - Database username: Choose 'Connect with a Secrets Manager ARN'"
echo "     - Secret ARN: $SECRET_ARN"
echo "     - Database name: $DB_NAME"
echo "  3. Run these queries:"
echo ""
echo "     -- Check rows exist:"
echo "     SELECT chunk_id, video_id, sequence, left(text, 60) AS text_preview,"
echo "            start_time, end_time"
echo "     FROM video_chunks ORDER BY video_id, sequence;"
echo ""
echo "     -- Verify 256 dimensions:"
echo "     SELECT chunk_id, array_length(string_to_array(embedding::text, ','), 1) AS dims"
echo "     FROM video_chunks LIMIT 3;"
echo ""
echo "     -- Test similarity search:"
echo "     SELECT chunk_id, left(text, 80) AS text_preview,"
echo "            1 - (embedding <=> (SELECT embedding FROM video_chunks LIMIT 1)) AS similarity"
echo "     FROM video_chunks"
echo "     ORDER BY embedding <=> (SELECT embedding FROM video_chunks LIMIT 1)"
echo "     LIMIT 5;"
echo ""
ENDPOINT=$(terraform -chdir="$TF_DIR" output -raw aurora_cluster_endpoint)
DB_NAME=$(terraform -chdir="$TF_DIR" output -raw aurora_db_name)
SECRET_ARN=$(terraform -chdir="$TF_DIR" output -raw aurora_secret_arn)
echo "  ── Option B: CloudShell VPC ──"
echo "  1. Open CloudShell > Create VPC environment (default VPC, cloudshell subnet + SG)"
echo "  2. Run:"
echo ""
echo "  ENDPOINT=\"$ENDPOINT\""
echo "  PASSWORD=\$(aws secretsmanager get-secret-value --secret-id $SECRET_ARN --query SecretString --output text | python3 -c \"import json,sys; print(json.load(sys.stdin)['password'])\")"
echo ""
echo "  PGPASSWORD=\$PASSWORD psql -h \"\$ENDPOINT\" -U ragadmin -d $DB_NAME -c \\"
echo "    \"SELECT chunk_id, video_id, sequence, left(text, 60) AS text_preview,"
echo "            start_time, end_time"
echo "     FROM video_chunks ORDER BY video_id, sequence;\""

echo ""
echo "=== 12. Embedding Lambda logs ==="
echo "  Check CloudWatch logs:"
echo "  aws logs tail /aws/lambda/$FUNC_NAME --since 10m"

echo ""
echo "========================================="
echo "  Results: $PASS_COUNT passed, $FAIL_COUNT failed"
echo "  (pgvector checks require CloudShell VPC)"
echo "========================================="

if [ "$FAIL_COUNT" -gt 0 ]; then
  exit 1
fi
