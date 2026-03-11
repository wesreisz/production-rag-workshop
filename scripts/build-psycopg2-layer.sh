#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LAYER_DIR="$PROJECT_ROOT/layers/psycopg2"

echo "=== Building psycopg2 Lambda layer ==="

mkdir -p "$LAYER_DIR"

echo "1. Installing psycopg2-binary and creating zip inside Docker..."
docker run --rm \
  --platform linux/amd64 \
  --entrypoint "" \
  -v "$LAYER_DIR:/output" \
  public.ecr.aws/lambda/python:3.11 \
  bash -c "pip install psycopg2-binary -t /tmp/python/lib/python3.11/site-packages/ --quiet && cd /tmp && yum install -y zip --quiet && zip -r9 /output/psycopg2-layer.zip python/ -q"

echo "2. Done!"
echo "   Layer zip: $LAYER_DIR/psycopg2-layer.zip"
ls -lh "$LAYER_DIR/psycopg2-layer.zip"
