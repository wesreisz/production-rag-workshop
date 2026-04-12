#!/usr/bin/env bash
set -euo pipefail

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null) || {
  echo "ERROR: Could not determine AWS account ID. Check your AWS credentials/profile." >&2
  exit 1
}

BUCKET_NAME="production-rag-tf-state-${ACCOUNT_ID}"
INFRA_DIR="$(cd "$(dirname "$0")/../infra" && pwd)"

echo "Account:      ${ACCOUNT_ID}"
echo "State bucket: ${BUCKET_NAME}"
echo ""

if [[ -f "${INFRA_DIR}/bootstrap/terraform.tfstate" ]]; then
  EXISTING_ACCOUNT=$(grep -oP '"account_id":\s*"\K[0-9]+' "${INFRA_DIR}/bootstrap/terraform.tfstate" 2>/dev/null | head -1 || true)
  if [[ -n "$EXISTING_ACCOUNT" && "$EXISTING_ACCOUNT" != "$ACCOUNT_ID" ]]; then
    echo "Removing stale bootstrap state from account ${EXISTING_ACCOUNT}"
    rm -f "${INFRA_DIR}/bootstrap/terraform.tfstate" "${INFRA_DIR}/bootstrap/terraform.tfstate.backup"
    rm -rf "${INFRA_DIR}/bootstrap/.terraform"
  fi
fi

VERSIONS_FILES=$(find "${INFRA_DIR}/environments" -name "versions.tf" 2>/dev/null)

for f in $VERSIONS_FILES; do
  if grep -q 'bucket\s*=' "$f"; then
    sed -i "s|bucket\s*=\s*\"[^\"]*\"|bucket         = \"${BUCKET_NAME}\"|" "$f"
    echo "Updated: ${f#"${INFRA_DIR}/"}"
    rm -rf "$(dirname "$f")/.terraform"
  fi
done

echo ""
echo "Done. Now run 'terraform init' and 'terraform apply' in your target directory."
