#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MODULE_DIR="$PROJECT_ROOT/modules/migration-module"

echo "=== Building migration module dependencies ==="

echo "1. Installing alembic + sqlalchemy into module directory..."
docker run --rm \
  --platform linux/amd64 \
  --entrypoint "" \
  -v "$MODULE_DIR:/module" \
  public.ecr.aws/lambda/python:3.11 \
  bash -c "pip install -r /module/requirements.txt -t /module/ --quiet --no-cache-dir"

echo "2. Cleaning up unnecessary files..."
find "$MODULE_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$MODULE_DIR" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true
find "$MODULE_DIR" -type d -name "tests" -path "*/alembic/tests" -exec rm -rf {} + 2>/dev/null || true

echo "3. Done!"
echo "   Module directory: $MODULE_DIR"
du -sh "$MODULE_DIR"
