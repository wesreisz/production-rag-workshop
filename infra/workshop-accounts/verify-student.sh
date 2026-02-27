#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/config.env"

# ------------------------------------------------------------------
# Usage
# ------------------------------------------------------------------
if [ $# -lt 1 ]; then
    echo "Usage: $0 <student_number>"
    echo ""
    echo "Examples:"
    echo "  $0 1       # Verify student-01 account"
    echo ""
    echo "Requires the student CLI profile to be configured:"
    echo "  aws configure --profile student-01"
    exit 1
fi

STUDENT_NUM=$1
PADDED=$(printf '%02d' "$STUDENT_NUM")
PROFILE="student-${PADDED}"

echo "==========================================="
echo " Verify Student $PADDED Account"
echo " Profile: $PROFILE"
echo "==========================================="
echo ""

PASS=0
FAIL=0
EXPECTED_FAIL=0

run_test() {
    local test_name="$1"
    local expect="$2"  # "pass" or "fail"
    shift 2

    printf "  %-45s" "$test_name..."
    OUTPUT=$("$@" 2>&1)
    EXIT_CODE=$?

    if [ "$expect" = "pass" ]; then
        if [ $EXIT_CODE -eq 0 ]; then
            echo "PASS"
            PASS=$((PASS + 1))
        else
            echo "FAIL"
            echo "    -> $OUTPUT" | head -3
            FAIL=$((FAIL + 1))
        fi
    else
        if [ $EXIT_CODE -ne 0 ]; then
            echo "BLOCKED (expected)"
            EXPECTED_FAIL=$((EXPECTED_FAIL + 1))
        else
            echo "NOT BLOCKED (unexpected!)"
            FAIL=$((FAIL + 1))
        fi
    fi
}

# ------------------------------------------------------------------
# Identity
# ------------------------------------------------------------------
echo "[Identity]"
run_test "STS get-caller-identity" pass \
    aws sts get-caller-identity --profile "$PROFILE"
echo ""

# ------------------------------------------------------------------
# Allowed Services
# ------------------------------------------------------------------
echo "[Allowed Services — should PASS]"

# S3
BUCKET_NAME="rag-workshop-verify-${PADDED}-$(date +%s)"
run_test "S3: create bucket" pass \
    aws s3 mb "s3://${BUCKET_NAME}" --profile "$PROFILE"

run_test "S3: upload object" pass \
    aws s3 cp - "s3://${BUCKET_NAME}/test.txt" --profile "$PROFILE" <<< "hello workshop"

run_test "S3: list objects" pass \
    aws s3 ls "s3://${BUCKET_NAME}/" --profile "$PROFILE"

run_test "S3: delete bucket" pass \
    aws s3 rb "s3://${BUCKET_NAME}" --force --profile "$PROFILE"

# Lambda
run_test "Lambda: list functions" pass \
    aws lambda list-functions --profile "$PROFILE"

# Step Functions
run_test "Step Functions: list state machines" pass \
    aws stepfunctions list-state-machines --profile "$PROFILE"

# SQS
run_test "SQS: list queues" pass \
    aws sqs list-queues --profile "$PROFILE"

# EventBridge
run_test "EventBridge: list rules" pass \
    aws events list-rules --profile "$PROFILE"

# Transcribe
run_test "Transcribe: list jobs" pass \
    aws transcribe list-transcription-jobs --profile "$PROFILE"

# Bedrock (Titan Embeddings)
BEDROCK_OUT=$(mktemp)
BEDROCK_IN=$(mktemp)
echo '{"inputText":"test embedding","dimensions":256,"normalize":true}' > "$BEDROCK_IN"

printf "  %-45s" "Bedrock: Titan Embeddings V2 invoke..."
if aws bedrock-runtime invoke-model \
    --model-id amazon.titan-embed-text-v2:0 \
    --content-type application/json \
    --accept application/json \
    --body "fileb://${BEDROCK_IN}" \
    "$BEDROCK_OUT" --profile "$PROFILE" > /dev/null 2>&1; then
    echo "PASS"
    PASS=$((PASS + 1))
    if [ -f "$BEDROCK_OUT" ] && [ -s "$BEDROCK_OUT" ]; then
        DIMS=$(python3 -c "import json; d=json.load(open('$BEDROCK_OUT')); print(len(d.get('embedding',[])))" 2>/dev/null || echo "?")
        echo "    -> Embedding dimensions: $DIMS"
    fi
else
    echo "FAIL"
    FAIL=$((FAIL + 1))
fi
rm -f "$BEDROCK_OUT" "$BEDROCK_IN"

# RDS
run_test "RDS: describe clusters" pass \
    aws rds describe-db-clusters --profile "$PROFILE"

# API Gateway
run_test "API Gateway: get rest apis" pass \
    aws apigateway get-rest-apis --profile "$PROFILE"

# CloudWatch Logs
run_test "CloudWatch Logs: describe log groups" pass \
    aws logs describe-log-groups --profile "$PROFILE"

# Secrets Manager
run_test "Secrets Manager: list secrets" pass \
    aws secretsmanager list-secrets --profile "$PROFILE"

# IAM
run_test "IAM: list roles" pass \
    aws iam list-roles --max-items 1 --profile "$PROFILE"

# DynamoDB
run_test "DynamoDB: list tables" pass \
    aws dynamodb list-tables --profile "$PROFILE"

# CloudTrail
run_test "CloudTrail: describe trails" pass \
    aws cloudtrail describe-trails --profile "$PROFILE"

echo ""

# ------------------------------------------------------------------
# Blocked Actions — should FAIL
# ------------------------------------------------------------------
echo "[Blocked Actions — should be DENIED]"

# Region lock (use region-scoped actions, not global ones like s3 ls)
run_test "Region lock: Lambda in us-west-2" fail \
    aws lambda list-functions --region us-west-2 --profile "$PROFILE"

run_test "Region lock: Lambda in eu-west-1" fail \
    aws lambda list-functions --region eu-west-1 --profile "$PROFILE"

run_test "Region lock: S3 create bucket us-west-2" fail \
    aws s3 mb "s3://rag-workshop-region-test-${PADDED}" --region us-west-2 --profile "$PROFILE"

# EC2 instances
run_test "EC2: run-instances blocked" fail \
    aws ec2 run-instances \
        --image-id ami-0abcdef1234567890 \
        --instance-type t3.micro \
        --profile "$PROFILE"

# SageMaker (not in allowlist)
run_test "SageMaker: blocked" fail \
    aws sagemaker list-endpoints --profile "$PROFILE"

# Organizations escape
run_test "Organizations: leave-organization blocked" fail \
    aws organizations leave-organization --profile "$PROFILE"

echo ""

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
TOTAL=$((PASS + FAIL + EXPECTED_FAIL))
echo "==========================================="
echo " Results"
echo "==========================================="
echo ""
echo "  Passed:            $PASS"
echo "  Blocked (expected): $EXPECTED_FAIL"
echo "  Failed:            $FAIL"
echo "  Total:             $TOTAL"
echo ""

if [ $FAIL -eq 0 ]; then
    echo "  ALL TESTS OK — student account is ready for the workshop."
else
    echo "  WARNING: $FAIL test(s) had unexpected results. Review above."
fi
echo ""
