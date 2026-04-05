#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LAYER_DIR="${PROJECT_ROOT}/layers/psycopg2"
TMP_DIR="${PROJECT_ROOT}/.layer-build-tmp"

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT
rm -rf "${TMP_DIR}"
mkdir -p "${TMP_DIR}"

echo "Building psycopg2 Lambda layer..."

docker run --rm \
  --entrypoint /bin/sh \
  --platform linux/amd64 \
  -v "${TMP_DIR}:/out" \
  public.ecr.aws/lambda/python:3.11 \
  -c "pip install psycopg2-binary -t /out/python/lib/python3.11/site-packages/"

mkdir -p "${LAYER_DIR}"

cd "${TMP_DIR}"
zip -r "${LAYER_DIR}/psycopg2-layer.zip" python/ -x "*.pyc" -x "*/__pycache__/*"

echo "Layer built: ${LAYER_DIR}/psycopg2-layer.zip"
