#!/usr/bin/env bash
set -euo pipefail

TF_DIR="$(cd "$(dirname "$0")/../../infra/environments/dev" && pwd)"
PASS_COUNT=0
FAIL_COUNT=0

pass() { echo "  PASS — $1"; PASS_COUNT=$((PASS_COUNT + 1)); }
fail() { echo "  FAIL — $1"; FAIL_COUNT=$((FAIL_COUNT + 1)); }

ENDPOINT=$(terraform -chdir="$TF_DIR" output -raw aurora_cluster_endpoint)
SECRET_ARN=$(terraform -chdir="$TF_DIR" output -raw aurora_secret_arn)
DB_NAME=$(terraform -chdir="$TF_DIR" output -raw aurora_db_name)
VPC_ID=$(terraform -chdir="$TF_DIR" output -raw vpc_id)
CS_SUBNET=$(terraform -chdir="$TF_DIR" output -raw cloudshell_subnet_id)
CS_SG=$(terraform -chdir="$TF_DIR" output -raw cloudshell_security_group_id)

echo "=== 1. Security groups ==="
LAMBDA_SG=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=production-rag-lambda-sg" "Name=vpc-id,Values=$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "None")
AURORA_SG=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=production-rag-aurora-sg" "Name=vpc-id,Values=$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "None")
CLOUDSHELL_SG=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=production-rag-cloudshell-sg" "Name=vpc-id,Values=$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "None")

if [ "$LAMBDA_SG" != "None" ] && [ -n "$LAMBDA_SG" ]; then
  pass "Lambda security group exists ($LAMBDA_SG)"
else
  fail "Lambda security group not found"
fi

if [ "$AURORA_SG" != "None" ] && [ -n "$AURORA_SG" ]; then
  pass "Aurora security group exists ($AURORA_SG)"
else
  fail "Aurora security group not found"
fi

if [ "$CLOUDSHELL_SG" != "None" ] && [ -n "$CLOUDSHELL_SG" ]; then
  pass "CloudShell security group exists ($CLOUDSHELL_SG)"
else
  fail "CloudShell security group not found"
fi

echo ""
echo "=== 2. VPC endpoints ==="
for SVC in s3 bedrock-runtime secretsmanager; do
  EP_STATE=$(aws ec2 describe-vpc-endpoints \
    --filters "Name=vpc-id,Values=$VPC_ID" "Name=service-name,Values=*${SVC}" \
    --query 'VpcEndpoints[0].State' --output text 2>/dev/null || echo "None")
  if [ "$EP_STATE" = "available" ]; then
    pass "$SVC endpoint is available"
  else
    fail "$SVC endpoint state: $EP_STATE"
  fi
done

echo ""
echo "=== 3. Aurora cluster ==="
CLUSTER_STATUS=$(aws rds describe-db-clusters \
  --db-cluster-identifier production-rag-vectordb \
  --query 'DBClusters[0].Status' --output text 2>/dev/null || echo "None")
if [ "$CLUSTER_STATUS" = "available" ]; then
  pass "Aurora cluster is available"
else
  fail "Aurora cluster status: $CLUSTER_STATUS"
fi

INSTANCE_CLASS=$(aws rds describe-db-instances \
  --db-instance-identifier production-rag-vectordb-instance \
  --query 'DBInstances[0].DBInstanceClass' --output text 2>/dev/null || echo "None")
if [ "$INSTANCE_CLASS" = "db.serverless" ]; then
  pass "Instance class is db.serverless"
else
  fail "Instance class: $INSTANCE_CLASS"
fi

echo ""
echo "=== 4. Secrets Manager ==="
SECRET_KEYS=$(aws secretsmanager get-secret-value \
  --secret-id "$SECRET_ARN" \
  --query 'SecretString' --output text 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
expected = {'host', 'port', 'dbname', 'username', 'password'}
present = expected & set(d.keys())
missing = expected - present
if missing:
    print(f'missing:{\" \".join(missing)}')
else:
    print('ok')
" 2>/dev/null || echo "error")

if [ "$SECRET_KEYS" = "ok" ]; then
  pass "Secret has all expected keys (host, port, dbname, username, password)"
else
  fail "Secret keys: $SECRET_KEYS"
fi

SECRET_HOST=$(aws secretsmanager get-secret-value \
  --secret-id "$SECRET_ARN" \
  --query 'SecretString' --output text 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['host'])" 2>/dev/null || echo "error")
if [ "$SECRET_HOST" = "$ENDPOINT" ]; then
  pass "Secret host matches Aurora endpoint"
else
  fail "Secret host ($SECRET_HOST) != endpoint ($ENDPOINT)"
fi

echo ""
echo "=== 5. psycopg2 Lambda layer ==="
LAYER_ARN=$(aws lambda list-layer-versions \
  --layer-name production-rag-psycopg2 \
  --query 'LayerVersions[0].LayerVersionArn' --output text 2>/dev/null || echo "None")
if [ "$LAYER_ARN" != "None" ] && [ -n "$LAYER_ARN" ]; then
  pass "psycopg2 layer deployed ($LAYER_ARN)"
else
  fail "psycopg2 layer not found"
fi

echo ""
echo "=== 6. NAT gateway ==="
NAT_STATE=$(aws ec2 describe-nat-gateways \
  --filter "Name=vpc-id,Values=$VPC_ID" "Name=state,Values=available" \
  --query 'NatGateways[0].State' --output text 2>/dev/null || echo "None")
if [ "$NAT_STATE" = "available" ]; then
  pass "NAT gateway is available"
else
  fail "NAT gateway state: $NAT_STATE"
fi

echo ""
echo "=== 7. CloudShell VPC environment setup ==="
echo "  To connect to Aurora, create a CloudShell VPC environment in the AWS Console:"
echo ""
echo "  1. Open CloudShell -> click (+) -> Create VPC environment"
echo "  2. VPC:             $VPC_ID"
echo "  3. Subnet:          $CS_SUBNET"
echo "  4. Security group:  $CS_SG"
echo ""
echo "  Then run:"
echo "  sudo yum install -y postgresql15"
echo "  ENDPOINT=\"$ENDPOINT\""
echo "  PASSWORD=\$(aws secretsmanager get-secret-value --secret-id $SECRET_ARN --query SecretString --output text | python3 -c \"import json,sys; print(json.load(sys.stdin)['password'])\")"
echo "  PGPASSWORD=\$PASSWORD psql -h \"\$ENDPOINT\" -U ragadmin -d ragdb -c \"SELECT 1;\""

echo ""
echo "=== 8. Migration files ==="
MIGRATION_FILE="$(cd "$(dirname "$0")/../.." && pwd)/migrations/versions/001_initial_schema.py"
if [ -f "$MIGRATION_FILE" ]; then
  pass "001_initial_schema.py exists"
else
  fail "001_initial_schema.py not found"
fi

echo ""
echo "=== 9. lambda-vpc module ==="
MODULE_DIR="$(cd "$(dirname "$0")/../../infra/modules/lambda-vpc" && pwd 2>/dev/null || echo "missing")"
if [ "$MODULE_DIR" != "missing" ] && [ -f "$MODULE_DIR/main.tf" ] && [ -f "$MODULE_DIR/variables.tf" ] && [ -f "$MODULE_DIR/outputs.tf" ]; then
  pass "lambda-vpc module has main.tf, variables.tf, outputs.tf"
else
  fail "lambda-vpc module incomplete or missing"
fi

echo ""
echo "========================================="
echo "  Results: $PASS_COUNT passed, $FAIL_COUNT failed"
echo "  (Database checks require CloudShell VPC environment)"
echo "========================================="

if [ "$FAIL_COUNT" -gt 0 ]; then
  exit 1
fi
