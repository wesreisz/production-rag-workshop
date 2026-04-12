#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MCP_CONFIG="${PROJECT_ROOT}/.cursor/mcp.json"

echo "=== MCP Configuration Helper ==="
echo ""

if ! aws sts get-caller-identity &>/dev/null; then
  echo "ERROR: AWS credentials not configured."
  echo "Run 'aws configure' or set AWS_PROFILE first."
  exit 1
fi

IDENTITY=$(aws sts get-caller-identity --output json)
ACCOUNT_ID=$(echo "${IDENTITY}" | python3 -c "import sys,json; print(json.load(sys.stdin)['Account'])")
echo "AWS Account: ${ACCOUNT_ID}"

API=$(aws apigateway get-rest-apis --region us-east-1 --output json \
  --query 'items[?tags.Project==`production-rag`] | [0]')

if [ "${API}" = "null" ] || [ -z "${API}" ]; then
  echo "ERROR: No API Gateway found with tag Project=production-rag."
  echo "Make sure Terraform has been applied in this account."
  exit 1
fi

API_ID=$(echo "${API}" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
API_NAME=$(echo "${API}" | python3 -c "import sys,json; print(json.load(sys.stdin)['name'])")
echo "API Gateway: ${API_NAME} (${API_ID})"

STAGE=$(aws apigateway get-stages --rest-api-id "${API_ID}" --region us-east-1 \
  --query 'item[0].stageName' --output text)
echo "Stage:       ${STAGE}"

API_ENDPOINT="https://${API_ID}.execute-api.us-east-1.amazonaws.com/${STAGE}"
echo "Endpoint:    ${API_ENDPOINT}"

API_KEY_VALUE=$(aws apigateway get-api-keys --region us-east-1 --include-values \
  --query 'items[?contains(name, `production-rag`)] | [0].value' --output text)

if [ "${API_KEY_VALUE}" = "None" ] || [ -z "${API_KEY_VALUE}" ]; then
  echo "ERROR: No API key found matching 'production-rag'."
  exit 1
fi

echo "API Key:     ${API_KEY_VALUE:0:8}..."
echo ""

echo "Verifying endpoint health..."
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  "${API_ENDPOINT}/health" -H "x-api-key: ${API_KEY_VALUE}")

if [ "${HTTP_STATUS}" != "200" ]; then
  echo "WARNING: Health check returned HTTP ${HTTP_STATUS}."
  echo "The endpoint may not be fully deployed yet."
else
  echo "Health check passed."
fi

echo ""

python3 -c "
import json, sys

path = '${MCP_CONFIG}'
with open(path) as f:
    config = json.load(f)

env = config['mcpServers']['video-knowledge']['env']
env['API_ENDPOINT'] = '${API_ENDPOINT}'
env['API_KEY'] = '${API_KEY_VALUE}'

with open(path, 'w') as f:
    json.dump(config, f, indent=2)
    f.write('\n')

print(f'Updated {path}')
"

echo ""
echo "Done! Restart the MCP server in Cursor for changes to take effect."
