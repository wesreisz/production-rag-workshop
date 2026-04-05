#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MODULE_DIR="${PROJECT_ROOT}/modules/migration-module"

echo "Installing migration module dependencies..."

docker run --rm \
  --entrypoint /bin/sh \
  --platform linux/amd64 \
  -v "${MODULE_DIR}:/module" \
  public.ecr.aws/lambda/python:3.11 \
  -c "pip install -r /module/requirements.txt -t /module --upgrade"

echo "Migration module dependencies installed."
