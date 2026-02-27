#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/config.env"

# ------------------------------------------------------------------
# Usage
# ------------------------------------------------------------------
if [ $# -lt 2 ]; then
    echo "Usage: $0 <start_number> <end_number>"
    echo ""
    echo "Examples:"
    echo "  $0 1 1      # Teardown student-01 only"
    echo "  $0 1 35     # Teardown student-01 through student-35"
    echo ""
    echo "This will:"
    echo "  1. Assume role into each student account"
    echo "  2. Delete IAM user and access keys"
    echo "  3. Close the account via Organizations"
    echo ""
    echo "WARNING: Account closure is irreversible after 90 days."
    exit 1
fi

START=$1
END=$2

echo "==========================================="
echo " Teardown Student Accounts ($START to $END)"
echo "==========================================="
echo ""
echo "WARNING: This will close AWS accounts."
echo "         Closed accounts enter SUSPENDED state for 90 days."
echo "         No charges accrue after closure."
echo ""
read -p "Type 'yes' to confirm: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi
echo ""

# ------------------------------------------------------------------
# Process each student
# ------------------------------------------------------------------
for N in $(seq "$START" "$END"); do
    PADDED=$(printf '%02d' "$N")
    ACCOUNT_NAME="${STUDENT_ACCOUNT_PREFIX}-${PADDED}"

    echo "--- Teardown Student $PADDED ---"

    # Look up account ID
    ACCOUNT_ID=$(aws organizations list-accounts \
        --region "$REGION" \
        --query "Accounts[?Name=='${ACCOUNT_NAME}' && Status=='ACTIVE'].Id" \
        --output text)

    if [ -z "$ACCOUNT_ID" ] || [ "$ACCOUNT_ID" = "None" ]; then
        echo "  -> Account '$ACCOUNT_NAME' not found or already closed. Skipping."
        echo ""
        continue
    fi

    echo "  Account ID: $ACCOUNT_ID"

    # ------------------------------------------------------------------
    # Assume role and clean up IAM resources
    # ------------------------------------------------------------------
    echo "  -> Assuming role for cleanup..."

    ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${CROSS_ACCOUNT_ROLE}"

    CREDS=$(aws sts assume-role \
        --role-arn "$ROLE_ARN" \
        --role-session-name "workshop-teardown-${PADDED}" \
        --duration-seconds 3600 \
        --query 'Credentials' \
        --output json 2>/dev/null) || {
        echo "  -> Could not assume role. Proceeding to close account directly."
        aws organizations close-account \
            --account-id "$ACCOUNT_ID" \
            --region "$REGION" 2>/dev/null || echo "  -> Close-account failed (may already be closing)."
        echo ""
        continue
    }

    export AWS_ACCESS_KEY_ID=$(echo "$CREDS" | python3 -c "import sys,json; print(json.load(sys.stdin)['AccessKeyId'])")
    export AWS_SECRET_ACCESS_KEY=$(echo "$CREDS" | python3 -c "import sys,json; print(json.load(sys.stdin)['SecretAccessKey'])")
    export AWS_SESSION_TOKEN=$(echo "$CREDS" | python3 -c "import sys,json; print(json.load(sys.stdin)['SessionToken'])")

    # Delete access keys for the workshop user
    EXISTING_KEYS=$(aws iam list-access-keys \
        --user-name "$STUDENT_IAM_USER" \
        --query 'AccessKeyMetadata[].AccessKeyId' \
        --output text 2>/dev/null) || EXISTING_KEYS=""

    for KEY_ID in $EXISTING_KEYS; do
        aws iam delete-access-key \
            --user-name "$STUDENT_IAM_USER" \
            --access-key-id "$KEY_ID" 2>/dev/null || true
        echo "  -> Deleted access key: $KEY_ID"
    done

    # Delete login profile
    aws iam delete-login-profile \
        --user-name "$STUDENT_IAM_USER" 2>/dev/null || true

    # Detach policies
    ATTACHED_POLICIES=$(aws iam list-attached-user-policies \
        --user-name "$STUDENT_IAM_USER" \
        --query 'AttachedPolicies[].PolicyArn' \
        --output text 2>/dev/null) || ATTACHED_POLICIES=""

    for POLICY_ARN in $ATTACHED_POLICIES; do
        aws iam detach-user-policy \
            --user-name "$STUDENT_IAM_USER" \
            --policy-arn "$POLICY_ARN" 2>/dev/null || true
        echo "  -> Detached policy: $POLICY_ARN"
    done

    # Delete IAM user
    aws iam delete-user \
        --user-name "$STUDENT_IAM_USER" 2>/dev/null || true
    echo "  -> Deleted IAM user: $STUDENT_IAM_USER"

    # Clear assumed-role credentials
    unset AWS_ACCESS_KEY_ID
    unset AWS_SECRET_ACCESS_KEY
    unset AWS_SESSION_TOKEN

    # ------------------------------------------------------------------
    # Close the account
    # ------------------------------------------------------------------
    echo "  -> Closing account..."
    aws organizations close-account \
        --account-id "$ACCOUNT_ID" \
        --region "$REGION" 2>/dev/null && {
        echo "  -> Account $ACCOUNT_ID closed (enters SUSPENDED state)."
    } || {
        echo "  -> Close-account call failed (may already be closing or have a constraint)."
    }

    # Clean up local credential file
    CRED_FILE="${STUDENTS_DIR}/student-${PADDED}-credentials.txt"
    if [ -f "$CRED_FILE" ]; then
        rm -f "$CRED_FILE"
        echo "  -> Deleted local credential file."
    fi

    echo ""
done

echo "==========================================="
echo " Teardown Complete"
echo "==========================================="
echo ""
echo "Closed accounts will remain in SUSPENDED state for 90 days."
echo "No charges will accrue after closure."
echo "Run ./list-students.sh to verify account status."
echo ""
