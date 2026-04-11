#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MODULE_DIR="${PROJECT_ROOT}/modules/migration-module"

echo "Installing migration module dependencies..."

if command -v docker &>/dev/null; then
  docker run --rm \
    --entrypoint /bin/sh \
    --platform linux/amd64 \
    -v "${MODULE_DIR}:/module" \
    public.ecr.aws/lambda/python:3.11 \
    -c "pip install -r /module/requirements.txt -t /module --upgrade"
else
  pip install \
    --platform manylinux2014_x86_64 \
    --implementation cp \
    --python-version 3.11 \
    --only-binary=:all: \
    --target "${MODULE_DIR}" \
    --upgrade \
    -r "${MODULE_DIR}/requirements.txt"
fi

echo "Migration module dependencies installed."
