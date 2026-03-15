#!/usr/bin/env bash
set -euo pipefail

MODULE_DIR="$(cd "$(dirname "$0")/../../modules/question-endpoint" && pwd)"
TF_DIR="$(cd "$(dirname "$0")/../../infra/environments/dev" && pwd)"
PASS_COUNT=0
FAIL_COUNT=0

pass() { echo "  PASS — $1"; PASS_COUNT=$((PASS_COUNT + 1)); }
fail() { echo "  FAIL — $1"; FAIL_COUNT=$((FAIL_COUNT + 1)); }

echo "=== 0. Unit test reminder ==="
echo "Run unit tests separately:"
echo "  cd $MODULE_DIR && python -m pytest tests/ -v"
echo ""

read -rp "Press Enter to continue with AWS verification or Ctrl+C to exit... "

API_URL=$(terraform -chdir="$TF_DIR" output -raw question_api_url 2>/dev/null || echo "")
API_KEY=$(terraform -chdir="$TF_DIR" output -raw question_api_key 2>/dev/null || echo "")

if [ -z "$API_URL" ] || [ -z "$API_KEY" ]; then
  fail "question_api_url or question_api_key output not found — has terraform apply been run?"
  echo ""
  echo "========================================="
  echo "  Results: $PASS_COUNT passed, $FAIL_COUNT failed"
  echo "========================================="
  exit 1
fi

echo ""
echo "=== 1. Question Lambda deployed ==="
FUNC_NAME=$(terraform -chdir="$TF_DIR" output -raw question_function_name 2>/dev/null || echo "")
FUNC_EXISTS=$(aws lambda get-function --function-name "$FUNC_NAME" --query 'Configuration.FunctionName' --output text 2>/dev/null || echo "None")
if [ "$FUNC_EXISTS" = "$FUNC_NAME" ]; then
  pass "Lambda function exists ($FUNC_NAME)"
else
  fail "Lambda function $FUNC_NAME not found"
fi

echo ""
echo "=== 2. Lambda is VPC-attached ==="
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
echo "=== 3. Lambda has psycopg2 layer ==="
LAYER_ARN=$(aws lambda get-function-configuration \
  --function-name "$FUNC_NAME" \
  --query 'Layers[0].Arn' --output text 2>/dev/null || echo "None")

if echo "$LAYER_ARN" | grep -q "psycopg2"; then
  pass "psycopg2 layer attached ($LAYER_ARN)"
else
  fail "psycopg2 layer not found on function"
fi

echo ""
echo "=== 4. API Gateway exists ==="
REST_API_ID=$(aws apigateway get-rest-apis \
  --query "items[?name=='production-rag-question-api'].id" --output text 2>/dev/null || echo "None")
if [ "$REST_API_ID" != "None" ] && [ -n "$REST_API_ID" ]; then
  pass "REST API exists (ID: $REST_API_ID)"
else
  fail "REST API 'production-rag-question-api' not found"
fi

echo ""
echo "=== 5. API Gateway has four routes ==="
RESOURCES=$(aws apigateway get-resources \
  --rest-api-id "$REST_API_ID" \
  --query 'items[].path' --output text 2>/dev/null || echo "")

for ROUTE in "/ask" "/videos" "/health" "/videos/{video_id}/ask"; do
  if echo "$RESOURCES" | grep -q "$ROUTE"; then
    pass "Route $ROUTE exists"
  else
    fail "Route $ROUTE not found"
  fi
done

echo ""
echo "=== 6. API key exists ==="
KEY_NAME=$(aws apigateway get-api-keys \
  --query "items[?name=='production-rag-question-api-key'].name" --output text 2>/dev/null || echo "None")
if [ "$KEY_NAME" != "None" ] && [ -n "$KEY_NAME" ]; then
  pass "API key exists ($KEY_NAME)"
else
  fail "API key 'production-rag-question-api-key' not found"
fi

echo ""
echo "=== 7. Usage plan has throttling ==="
PLAN_ID=$(aws apigateway get-usage-plans \
  --query "items[?name=='production-rag-question-api-usage-plan'].id" --output text 2>/dev/null || echo "None")
if [ "$PLAN_ID" != "None" ] && [ -n "$PLAN_ID" ]; then
  RATE=$(aws apigateway get-usage-plan --usage-plan-id "$PLAN_ID" \
    --query 'throttle.rateLimit' --output text 2>/dev/null || echo "0")
  BURST=$(aws apigateway get-usage-plan --usage-plan-id "$PLAN_ID" \
    --query 'throttle.burstLimit' --output text 2>/dev/null || echo "0")
  QUOTA=$(aws apigateway get-usage-plan --usage-plan-id "$PLAN_ID" \
    --query 'quota.limit' --output text 2>/dev/null || echo "0")

  if [ "$RATE" = "50.0" ] || [ "$RATE" = "50" ]; then
    pass "Rate limit is 50/s"
  else
    fail "Rate limit is $RATE, expected 50"
  fi

  if [ "$BURST" = "100" ]; then
    pass "Burst limit is 100"
  else
    fail "Burst limit is $BURST, expected 100"
  fi

  if [ "$QUOTA" = "10000" ]; then
    pass "Daily quota is 10000"
  else
    fail "Daily quota is $QUOTA, expected 10000"
  fi
else
  fail "Usage plan not found"
fi

echo ""
echo "=== 8. GET /health returns healthy ==="
HEALTH_RESP=$(curl -s -H "x-api-key: $API_KEY" "$API_URL/health")
HEALTH_STATUS=$(echo "$HEALTH_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "error")
if [ "$HEALTH_STATUS" = "healthy" ]; then
  pass "GET /health returns {\"status\": \"healthy\"}"
else
  fail "GET /health returned: $HEALTH_RESP"
fi

echo ""
echo "=== 9. Request without API key returns 403 ==="
NO_KEY_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/health")
if [ "$NO_KEY_CODE" = "403" ]; then
  pass "Request without API key returns 403"
else
  fail "Request without API key returned $NO_KEY_CODE, expected 403"
fi

echo ""
echo "=== 10. GET /videos returns video list ==="
VIDEOS_RESP=$(curl -s -H "x-api-key: $API_KEY" "$API_URL/videos")
VIDEO_COUNT=$(echo "$VIDEOS_RESP" | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('videos',[])))" 2>/dev/null || echo "0")
if [ "$VIDEO_COUNT" -gt 0 ]; then
  pass "GET /videos returned $VIDEO_COUNT video(s)"
else
  fail "GET /videos returned 0 videos"
fi

FIRST_VIDEO_ID=$(echo "$VIDEOS_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['videos'][0]['video_id'])" 2>/dev/null || echo "")

echo ""
echo "=== 11. POST /ask returns ranked chunks ==="
ASK_RESP=$(curl -s -X POST "$API_URL/ask" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d '{"question": "What is this video about?", "top_k": 3}')
ASK_RESULTS=$(echo "$ASK_RESP" | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('results',[])))" 2>/dev/null || echo "0")
ASK_QUESTION=$(echo "$ASK_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('question',''))" 2>/dev/null || echo "")

if [ "$ASK_RESULTS" -gt 0 ] && [ "$ASK_QUESTION" = "What is this video about?" ]; then
  pass "POST /ask returned $ASK_RESULTS result(s) with question echo"
else
  fail "POST /ask response: $ASK_RESP"
fi

echo ""
echo "=== 12. Similarity values are between 0 and 1 ==="
SIM_CHECK=$(echo "$ASK_RESP" | python3 -c "
import json, sys
data = json.load(sys.stdin)
results = data.get('results', [])
if not results:
    print('no_results')
elif all(0.0 <= r['similarity'] <= 1.0 for r in results):
    print('ok')
else:
    print('out_of_range')
" 2>/dev/null || echo "error")

if [ "$SIM_CHECK" = "ok" ]; then
  pass "All similarity scores are between 0.0 and 1.0"
else
  fail "Similarity check: $SIM_CHECK"
fi

echo ""
echo "=== 13. POST /videos/{video_id}/ask returns scoped results ==="
if [ -n "$FIRST_VIDEO_ID" ]; then
  VIDEO_ASK_RESP=$(curl -s -X POST "$API_URL/videos/$FIRST_VIDEO_ID/ask" \
    -H "Content-Type: application/json" \
    -H "x-api-key: $API_KEY" \
    -d '{"question": "What is this about?", "top_k": 3}')
  VIDEO_ASK_VID=$(echo "$VIDEO_ASK_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('video_id',''))" 2>/dev/null || echo "")
  VIDEO_ASK_COUNT=$(echo "$VIDEO_ASK_RESP" | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('results',[])))" 2>/dev/null || echo "0")
  VIDEO_ASK_SCOPED=$(echo "$VIDEO_ASK_RESP" | python3 -c "
import json, sys
data = json.load(sys.stdin)
vid = data.get('video_id','')
results = data.get('results', [])
if not results:
    print('empty')
elif all(r['video_id'] == vid for r in results):
    print('scoped')
else:
    print('mixed')
" 2>/dev/null || echo "error")

  if [ "$VIDEO_ASK_VID" = "$FIRST_VIDEO_ID" ]; then
    pass "Response includes video_id=$FIRST_VIDEO_ID"
  else
    fail "Response video_id=$VIDEO_ASK_VID, expected $FIRST_VIDEO_ID"
  fi

  if [ "$VIDEO_ASK_SCOPED" = "scoped" ] || [ "$VIDEO_ASK_SCOPED" = "empty" ]; then
    pass "Results are scoped to the requested video ($VIDEO_ASK_COUNT result(s))"
  else
    fail "Results contain chunks from other videos"
  fi
else
  fail "No video_id available to test video-scoped ask"
fi

echo ""
echo "=== 14. Validation: empty question returns 400 ==="
VALID_RESP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API_URL/ask" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d '{"question": ""}')
if [ "$VALID_RESP" = "400" ]; then
  pass "Empty question returns 400"
else
  fail "Empty question returned $VALID_RESP, expected 400"
fi

VALID_MSG=$(curl -s -X POST "$API_URL/ask" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d '{"question": ""}' | python3 -c "import json,sys; print(json.load(sys.stdin).get('error',''))" 2>/dev/null || echo "")
if [ "$VALID_MSG" = "question is required" ]; then
  pass "Error message: \"question is required\""
else
  fail "Error message: \"$VALID_MSG\""
fi

echo ""
echo "=== 15. Unknown route returns 404 ==="
UNKNOWN_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "x-api-key: $API_KEY" "$API_URL/nonexistent")
if [ "$UNKNOWN_CODE" = "403" ] || [ "$UNKNOWN_CODE" = "404" ]; then
  pass "Unknown route returns $UNKNOWN_CODE"
else
  fail "Unknown route returned $UNKNOWN_CODE, expected 403 or 404"
fi

echo ""
echo "========================================="
echo "  Results: $PASS_COUNT passed, $FAIL_COUNT failed"
echo "========================================="

if [ -n "$API_URL" ] && [ -n "$API_KEY" ]; then
  echo ""
  echo "You can curl the question endpoint directly with:"
  echo ""
  echo "  # Health check"
  echo "  curl -s \"$API_URL/health\" \\"
  echo "    -H \"x-api-key: $API_KEY\" | jq"
  echo ""
  echo "  # List indexed videos"
  echo "  curl -s \"$API_URL/videos\" \\"
  echo "    -H \"x-api-key: $API_KEY\" | jq"
  echo ""
  echo "  # Ask a question across all videos"
  echo "  curl -s -X POST \"$API_URL/ask\" \\"
  echo "    -H \"Content-Type: application/json\" \\"
  echo "    -H \"x-api-key: $API_KEY\" \\"
  echo "    -d '{\"question\": \"What is this video about?\", \"top_k\": 5}' | jq"
  echo ""
  echo "  # Ask with similarity threshold"
  echo "  curl -s -X POST \"$API_URL/ask\" \\"
  echo "    -H \"Content-Type: application/json\" \\"
  echo "    -H \"x-api-key: $API_KEY\" \\"
  echo "    -d '{\"question\": \"What is this video about?\", \"top_k\": 5, \"similarity_threshold\": 0.3}' | jq"
  echo ""
  echo "  # Ask with speaker filter"
  echo "  curl -s -X POST \"$API_URL/ask\" \\"
  echo "    -H \"Content-Type: application/json\" \\"
  echo "    -H \"x-api-key: $API_KEY\" \\"
  echo "    -d '{\"question\": \"What is this video about?\", \"top_k\": 3, \"filters\": {\"speaker\": \"Wesley Reisz\"}}' | jq"
  echo ""
  if [ -n "$FIRST_VIDEO_ID" ]; then
    echo "  # Ask a question scoped to a specific video"
    echo "  curl -s -X POST \"$API_URL/videos/$FIRST_VIDEO_ID/ask\" \\"
    echo "    -H \"Content-Type: application/json\" \\"
    echo "    -H \"x-api-key: $API_KEY\" \\"
    echo "    -d '{\"question\": \"Who is the speaker?\", \"top_k\": 3}' | jq"
    echo ""
  fi
fi

if [ "$FAIL_COUNT" -gt 0 ]; then
  exit 1
fi
