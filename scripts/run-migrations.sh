#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TF_DIR="$PROJECT_ROOT/infra/environments/dev"

echo "=== Reading connection details from Terraform outputs ==="

ENDPOINT=$(terraform -chdir="$TF_DIR" output -raw aurora_cluster_endpoint)
DB_NAME=$(terraform -chdir="$TF_DIR" output -raw aurora_db_name)
DB_USER="ragadmin"
DB_PORT="5432"

if [ -z "${PGPASSWORD:-}" ]; then
  echo "ERROR: PGPASSWORD environment variable is not set."
  echo "Usage: PGPASSWORD=YourPassword bash scripts/run-migrations.sh"
  exit 1
fi

export DATABASE_URL="postgresql://${DB_USER}:${PGPASSWORD}@${ENDPOINT}:${DB_PORT}/${DB_NAME}"

echo "  Host: $ENDPOINT"
echo "  DB:   $DB_NAME"
echo "  User: $DB_USER"

echo ""
echo "=== Running Alembic migrations ==="

cd "$PROJECT_ROOT/migrations"
alembic upgrade head

echo ""
echo "=== Migrations complete ==="
