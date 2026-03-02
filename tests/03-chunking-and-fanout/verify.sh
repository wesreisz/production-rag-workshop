#!/usr/bin/env bash
set -euo pipefail

MODULE_DIR="$(cd "$(dirname "$0")/../../modules/chunking-module" && pwd)"
TF_DIR="$(cd "$(dirname "$0")/../../infra/environments/dev" && pwd)"
SAMPLES_DIR="$(cd "$(dirname "$0")/../../samples" && pwd)"

echo "=== 0. Unit test reminder ==="
echo "Run unit tests separately:"
echo "  cd $MODULE_DIR && python -m pytest tests/ -v"
echo ""

BUCKET=$(terraform -chdir="$TF_DIR" output -raw media_bucket_name)
STATE_MACHINE=$(terraform -chdir="$TF_DIR" output -raw state_machine_arn)

EXISTING=$( (aws s3 ls "s3://${BUCKET}/uploads/test-chunk-" --recursive 2>/dev/null || true) | wc -l | tr -d ' ')
RUN_NUM=$(printf "%03d" $((EXISTING + 1)))
UPLOAD_NAME="test-chunk-${RUN_NUM}.mp3"
VIDEO_ID="test-chunk-${RUN_NUM}"

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
echo "=== 5. Verify chunks exist in S3 ==="
CHUNK_COUNT=$( (aws s3 ls "s3://${BUCKET}/chunks/${VIDEO_ID}/" 2>/dev/null || true) | wc -l | tr -d ' ')

if [ "$CHUNK_COUNT" -ge 1 ]; then
  echo "PASS — found ${CHUNK_COUNT} chunk file(s) at s3://${BUCKET}/chunks/${VIDEO_ID}/"
else
  echo "FAIL — no chunks found at s3://${BUCKET}/chunks/${VIDEO_ID}/"
  exit 1
fi

echo ""
echo "=== 6. Verify chunk content ==="
FIRST_CHUNK_KEY="chunks/${VIDEO_ID}/chunk-001.json"
aws s3 cp "s3://${BUCKET}/${FIRST_CHUNK_KEY}" /tmp/chunk-001.json --quiet

python3 -c "
import json, sys

c = json.load(open('/tmp/chunk-001.json'))

checks = []
checks.append(('chunk_id present', bool(c.get('chunk_id'))))
checks.append(('video_id matches', c.get('video_id') == '${VIDEO_ID}'))
checks.append(('sequence is 1', c.get('sequence') == 1))
checks.append(('text non-empty', bool(c.get('text', '').strip())))
checks.append(('word_count > 0', c.get('word_count', 0) > 0))
checks.append(('start_time < end_time', c.get('start_time', 1) < c.get('end_time', 0)))
checks.append(('metadata.source_s3_key present', bool(c.get('metadata', {}).get('source_s3_key'))))
checks.append(('metadata.total_chunks > 0', c.get('metadata', {}).get('total_chunks', 0) > 0))

all_pass = True
for name, result in checks:
    status = 'PASS' if result else 'FAIL'
    if not result:
        all_pass = False
    print(f'  {status} — {name}')

print()
print(f'  Text preview: {c[\"text\"][:150]}')

if not all_pass:
    sys.exit(1)
"

echo ""
echo "=== 7. Verify execution output has chunk_keys ==="
aws stepfunctions describe-execution \
  --execution-arn "$EXECUTION_ARN" \
  --query 'output' \
  --output text > /tmp/sfn-output.json

python3 -c "
import json, sys

output = json.loads(open('/tmp/sfn-output.json').read())
chunking = output.get('chunking', {}).get('detail', {})

chunk_keys = chunking.get('chunk_keys', [])
chunk_count = chunking.get('chunk_count', 0)

if chunk_count > 0 and len(chunk_keys) == chunk_count:
    print(f'PASS — chunk_count={chunk_count}, chunk_keys has {len(chunk_keys)} entries')
    for k in chunk_keys:
        print(f'  {k}')
else:
    print(f'FAIL — chunk_count={chunk_count}, chunk_keys length={len(chunk_keys)}')
    sys.exit(1)
"

echo ""
echo "=== 8. Verify Step Functions execution history ==="
STATES=$(aws stepfunctions get-execution-history \
  --execution-arn "$EXECUTION_ARN" \
  --query "events[?type=='TaskStateExited'].stateExitedEventDetails.name" \
  --output text)

echo "  States visited: $STATES"

if echo "$STATES" | grep -q "ChunkTranscript"; then
  echo "PASS — ChunkTranscript state executed"
else
  echo "FAIL — ChunkTranscript state not found in execution history"
  exit 1
fi

echo ""
echo "=== All checks passed ==="
