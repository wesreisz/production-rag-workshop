#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT/infra/environments/dev"

ENDPOINT=$(terraform output -raw aurora_cluster_endpoint)
SECRET_ARN=$(terraform output -raw aurora_secret_arn)
DB_NAME=$(terraform output -raw aurora_db_name)

SECRET_JSON=$(aws secretsmanager get-secret-value --secret-id "$SECRET_ARN" --query SecretString --output text)
USERNAME=$(echo "$SECRET_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['username'])")
PASSWORD=$(echo "$SECRET_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin)['password'])")

export DATABASE_URL="postgresql://${USERNAME}:${PASSWORD}@${ENDPOINT}:5432/${DB_NAME}"

cd "$PROJECT_ROOT/modules/migration-module/migrations"
alembic upgrade head
