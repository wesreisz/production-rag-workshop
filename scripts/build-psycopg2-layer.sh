#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="$PROJECT_ROOT/layers/psycopg2"

mkdir -p "$OUTPUT_DIR"

if command -v docker &> /dev/null; then
  echo "Building psycopg2 layer using Docker..."
  docker run --rm --platform linux/amd64 \
    -v "$OUTPUT_DIR:/out" \
    public.ecr.aws/lambda/python:3.11 \
    pip install psycopg2-binary -t /out/python/lib/python3.11/site-packages/
else
  echo "Docker not available, using pip with platform targeting..."
  mkdir -p "$OUTPUT_DIR/python/lib/python3.11/site-packages/"
  pip install psycopg2-binary \
    -t "$OUTPUT_DIR/python/lib/python3.11/site-packages/" \
    --platform manylinux2014_x86_64 \
    --only-binary=:all: \
    --python-version 3.11 \
    --implementation cp
fi

cd "$OUTPUT_DIR" && zip -r psycopg2-layer.zip python/

echo "psycopg2 layer built at $OUTPUT_DIR/psycopg2-layer.zip"
