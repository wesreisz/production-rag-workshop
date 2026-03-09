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
DB_USER="ragadmin"

if [ -z "${PGPASSWORD:-}" ]; then
  echo "ERROR: PGPASSWORD not set."
  echo "Usage: PGPASSWORD=YourPassword bash tests/04-embed-and-store-infra/verify.sh"
  exit 1
fi

echo "=== 1. Security groups ==="
LAMBDA_SG=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=production-rag-lambda-sg" "Name=vpc-id,Values=$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "None")
AURORA_SG=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=production-rag-aurora-sg" "Name=vpc-id,Values=$VPC_ID" \
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

PUBLICLY=$(aws rds describe-db-instances \
  --db-instance-identifier production-rag-vectordb-instance \
  --query 'DBInstances[0].PubliclyAccessible' --output text 2>/dev/null || echo "None")
if [ "$PUBLICLY" = "True" ]; then
  pass "Aurora instance is publicly accessible"
else
  fail "Aurora instance publicly_accessible: $PUBLICLY"
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
echo "=== 6. Database connectivity (psql) ==="
PSQL_TEST=$(PGPASSWORD="$PGPASSWORD" psql -h "$ENDPOINT" -U "$DB_USER" -d "$DB_NAME" -t -A -c "SELECT 1" 2>/dev/null || echo "error")
if [ "$PSQL_TEST" = "1" ]; then
  pass "psql connects to Aurora"
else
  fail "psql connection failed"
fi

echo ""
echo "=== 7. pgvector extension ==="
PGVECTOR=$(PGPASSWORD="$PGPASSWORD" psql -h "$ENDPOINT" -U "$DB_USER" -d "$DB_NAME" -t -A \
  -c "SELECT extname FROM pg_extension WHERE extname = 'vector'" 2>/dev/null || echo "")
if [ "$PGVECTOR" = "vector" ]; then
  pass "pgvector extension is enabled"
else
  fail "pgvector extension not found"
fi

echo ""
echo "=== 8. video_chunks table ==="
TABLE=$(PGPASSWORD="$PGPASSWORD" psql -h "$ENDPOINT" -U "$DB_USER" -d "$DB_NAME" -t -A \
  -c "SELECT table_name FROM information_schema.tables WHERE table_name = 'video_chunks'" 2>/dev/null || echo "")
if [ "$TABLE" = "video_chunks" ]; then
  pass "video_chunks table exists"
else
  fail "video_chunks table not found"
fi

echo ""
echo "=== 9. Indexes ==="
for IDX in idx_video_chunks_embedding idx_video_chunks_video_id idx_video_chunks_speaker; do
  IDX_EXISTS=$(PGPASSWORD="$PGPASSWORD" psql -h "$ENDPOINT" -U "$DB_USER" -d "$DB_NAME" -t -A \
    -c "SELECT indexname FROM pg_indexes WHERE indexname = '${IDX}'" 2>/dev/null || echo "")
  if [ "$IDX_EXISTS" = "$IDX" ]; then
    pass "$IDX exists"
  else
    fail "$IDX not found"
  fi
done

echo ""
echo "=== 10. Embedding column type ==="
COL_TYPE=$(PGPASSWORD="$PGPASSWORD" psql -h "$ENDPOINT" -U "$DB_USER" -d "$DB_NAME" -t -A \
  -c "SELECT udt_name FROM information_schema.columns WHERE table_name = 'video_chunks' AND column_name = 'embedding'" 2>/dev/null || echo "")
if [ "$COL_TYPE" = "vector" ]; then
  pass "embedding column is vector type"
else
  fail "embedding column type: $COL_TYPE"
fi

echo ""
echo "=== 11. Alembic version ==="
ALEMBIC_VER=$(PGPASSWORD="$PGPASSWORD" psql -h "$ENDPOINT" -U "$DB_USER" -d "$DB_NAME" -t -A \
  -c "SELECT version_num FROM alembic_version" 2>/dev/null || echo "")
if [ -n "$ALEMBIC_VER" ]; then
  pass "Alembic version tracked: $ALEMBIC_VER"
else
  fail "Alembic version table empty or missing"
fi

echo ""
echo "=== 12. Migration files ==="
MIGRATION_FILE="$(cd "$(dirname "$0")/../.." && pwd)/migrations/versions/001_initial_schema.py"
if [ -f "$MIGRATION_FILE" ]; then
  pass "001_initial_schema.py exists"
else
  fail "001_initial_schema.py not found"
fi

echo ""
echo "=== 13. lambda-vpc module ==="
MODULE_DIR="$(cd "$(dirname "$0")/../../infra/modules/lambda-vpc" && pwd 2>/dev/null || echo "missing")"
if [ "$MODULE_DIR" != "missing" ] && [ -f "$MODULE_DIR/main.tf" ] && [ -f "$MODULE_DIR/variables.tf" ] && [ -f "$MODULE_DIR/outputs.tf" ]; then
  pass "lambda-vpc module has main.tf, variables.tf, outputs.tf"
else
  fail "lambda-vpc module incomplete or missing"
fi

echo ""
echo "========================================="
echo "  Results: $PASS_COUNT passed, $FAIL_COUNT failed"
echo "========================================="

if [ "$FAIL_COUNT" -gt 0 ]; then
  exit 1
fi
