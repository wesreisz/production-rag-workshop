#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INFRA_DIR="${PROJECT_ROOT}/infra/environments/dev"
MIGRATIONS_DIR="${PROJECT_ROOT}/modules/migration-module/migrations"

ENDPOINT=$(terraform -chdir="${INFRA_DIR}" output -raw aurora_cluster_endpoint)
DB_NAME=$(terraform -chdir="${INFRA_DIR}" output -raw aurora_db_name)
SECRET_ARN=$(terraform -chdir="${INFRA_DIR}" output -raw aurora_secret_arn)

SECRET=$(aws secretsmanager get-secret-value --secret-id "${SECRET_ARN}" --query SecretString --output text)
USERNAME=$(echo "${SECRET}" | python3 -c "import sys,json; print(json.load(sys.stdin)['username'])")
PASSWORD=$(echo "${SECRET}" | python3 -c "import sys,json; print(json.load(sys.stdin)['password'])")

export DATABASE_URL="postgresql+psycopg2://${USERNAME}:${PASSWORD}@${ENDPOINT}:5432/${DB_NAME}"

cd "${PROJECT_ROOT}/modules/migration-module"
alembic -c migrations/alembic.ini upgrade head
