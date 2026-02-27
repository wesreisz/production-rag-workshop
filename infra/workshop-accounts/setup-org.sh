#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/config.env"

echo "==========================================="
echo " Workshop Organization Setup"
echo "==========================================="
echo ""

# ------------------------------------------------------------------
# 1. Ensure AWS Organizations exists
# ------------------------------------------------------------------
echo "[1/5] Checking AWS Organizations..."

if aws organizations describe-organization --region "$REGION" 2>/dev/null; then
    echo "  -> Organization already exists."
else
    echo "  -> Creating Organization with ALL features..."
    aws organizations create-organization \
        --feature-set ALL \
        --region "$REGION"
    echo "  -> Organization created."
fi

ORG_ID=$(aws organizations describe-organization \
    --region "$REGION" \
    --query 'Organization.Id' \
    --output text)
echo "  -> Organization ID: $ORG_ID"
echo ""

# ------------------------------------------------------------------
# 2. Get Root OU ID
# ------------------------------------------------------------------
echo "[2/5] Getting Root OU..."

ROOT_ID=$(aws organizations list-roots \
    --region "$REGION" \
    --query 'Roots[0].Id' \
    --output text)
echo "  -> Root ID: $ROOT_ID"
echo ""

# ------------------------------------------------------------------
# 3. Create workshop-students OU (if not exists)
# ------------------------------------------------------------------
echo "[3/5] Checking for '$OU_NAME' OU..."

EXISTING_OU_ID=$(aws organizations list-organizational-units-for-parent \
    --parent-id "$ROOT_ID" \
    --region "$REGION" \
    --query "OrganizationalUnits[?Name=='${OU_NAME}'].Id" \
    --output text)

if [ -n "$EXISTING_OU_ID" ] && [ "$EXISTING_OU_ID" != "None" ]; then
    OU_ID="$EXISTING_OU_ID"
    echo "  -> OU '$OU_NAME' already exists: $OU_ID"
else
    echo "  -> Creating OU '$OU_NAME'..."
    OU_ID=$(aws organizations create-organizational-unit \
        --parent-id "$ROOT_ID" \
        --name "$OU_NAME" \
        --region "$REGION" \
        --query 'OrganizationalUnit.Id' \
        --output text)
    echo "  -> Created OU: $OU_ID"
fi
echo ""

# ------------------------------------------------------------------
# 4. Create SCP (if not exists)
# ------------------------------------------------------------------
echo "[4/5] Checking for Workshop SCP..."

SCP_NAME="WorkshopServicesAllowlist"

EXISTING_SCP_ID=$(aws organizations list-policies \
    --filter SERVICE_CONTROL_POLICY \
    --region "$REGION" \
    --query "Policies[?Name=='${SCP_NAME}'].Id" \
    --output text)

SCP_CONTENT=$(cat "$SCRIPT_DIR/scp-workshop.json")

if [ -n "$EXISTING_SCP_ID" ] && [ "$EXISTING_SCP_ID" != "None" ]; then
    SCP_ID="$EXISTING_SCP_ID"
    echo "  -> SCP '$SCP_NAME' already exists: $SCP_ID"
    echo "  -> Updating SCP content..."
    aws organizations update-policy \
        --policy-id "$SCP_ID" \
        --content "$SCP_CONTENT" \
        --region "$REGION" > /dev/null
    echo "  -> SCP updated."
else
    echo "  -> Creating SCP '$SCP_NAME'..."
    SCP_ID=$(aws organizations create-policy \
        --name "$SCP_NAME" \
        --description "Restricts workshop student accounts to only required AWS services and us-east-1" \
        --type SERVICE_CONTROL_POLICY \
        --content "$SCP_CONTENT" \
        --region "$REGION" \
        --query 'Policy.PolicySummary.Id' \
        --output text)
    echo "  -> Created SCP: $SCP_ID"
fi
echo ""

# ------------------------------------------------------------------
# 5. Attach SCP to workshop OU (if not already attached)
# ------------------------------------------------------------------
echo "[5/5] Attaching SCP to OU..."

ATTACHED=$(aws organizations list-policies-for-target \
    --target-id "$OU_ID" \
    --filter SERVICE_CONTROL_POLICY \
    --region "$REGION" \
    --query "Policies[?Id=='${SCP_ID}'].Id" \
    --output text)

if [ -n "$ATTACHED" ] && [ "$ATTACHED" != "None" ]; then
    echo "  -> SCP already attached to OU."
else
    aws organizations attach-policy \
        --policy-id "$SCP_ID" \
        --target-id "$OU_ID" \
        --region "$REGION"
    echo "  -> SCP attached to OU '$OU_NAME'."
fi
echo ""

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
echo "==========================================="
echo " Setup Complete"
echo "==========================================="
echo ""
echo "  Organization ID : $ORG_ID"
echo "  Root OU ID      : $ROOT_ID"
echo "  Workshop OU ID  : $OU_ID"
echo "  SCP ID          : $SCP_ID"
echo ""
echo "Next step: ./create-students.sh 1 1"
echo ""
