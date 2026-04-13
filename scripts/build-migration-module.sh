#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TARGET_DIR="$PROJECT_ROOT/modules/migration-module"

if command -v docker &> /dev/null; then
  echo "Building migration module dependencies using Docker..."
  docker run --rm --platform linux/amd64 \
    -v "$TARGET_DIR:/out" \
    -w /out \
    public.ecr.aws/lambda/python:3.11 \
    pip install -r requirements.txt -t /out/
else
  echo "Docker not available, using pip with platform targeting..."
  pip install -r "$TARGET_DIR/requirements.txt" \
    -t "$TARGET_DIR/" \
    --platform manylinux2014_x86_64 \
    --only-binary=:all: \
    --python-version 3.11 \
    --implementation cp
fi

echo "Migration module dependencies installed to $TARGET_DIR"
