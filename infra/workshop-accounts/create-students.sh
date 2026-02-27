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
    echo "  $0 1 1      # Create student-01 only"
    echo "  $0 1 35     # Create student-01 through student-35"
    echo "  $0 5 10     # Create student-05 through student-10"
    exit 1
fi

START=$1
END=$2

echo "==========================================="
echo " Create Student Accounts ($START to $END)"
echo "==========================================="
echo ""

# ------------------------------------------------------------------
# Get the workshop OU ID
# ------------------------------------------------------------------
ROOT_ID=$(aws organizations list-roots \
    --region "$REGION" \
    --query 'Roots[0].Id' \
    --output text)

OU_ID=$(aws organizations list-organizational-units-for-parent \
    --parent-id "$ROOT_ID" \
    --region "$REGION" \
    --query "OrganizationalUnits[?Name=='${OU_NAME}'].Id" \
    --output text)

if [ -z "$OU_ID" ] || [ "$OU_ID" = "None" ]; then
    echo "ERROR: OU '$OU_NAME' not found. Run setup-org.sh first."
    exit 1
fi

echo "Workshop OU: $OU_ID"
echo ""

# ------------------------------------------------------------------
# Initialize CSV if it doesn't exist
# ------------------------------------------------------------------
if [ ! -f "$STUDENTS_CSV" ]; then
    echo "number,account_id,account_name,email,status" > "$STUDENTS_CSV"
fi

# ------------------------------------------------------------------
# Fetch existing accounts to check for duplicates
# ------------------------------------------------------------------
EXISTING_ACCOUNTS=$(aws organizations list-accounts \
    --region "$REGION" \
    --query 'Accounts[].Name' \
    --output text)

# ------------------------------------------------------------------
# Create accounts
# ------------------------------------------------------------------
for N in $(seq "$START" "$END"); do
    PADDED=$(printf '%02d' "$N")
    ACCOUNT_NAME="${STUDENT_ACCOUNT_PREFIX}-${PADDED}"
    EMAIL_LOCAL="${EMAIL_BASE%@*}"
    EMAIL_DOMAIN="${EMAIL_BASE#*@}"
    ACCOUNT_EMAIL="${EMAIL_LOCAL}+workshop-student-${PADDED}@${EMAIL_DOMAIN}"

    echo "--- Student $PADDED ---"
    echo "  Account: $ACCOUNT_NAME"
    echo "  Email:   $ACCOUNT_EMAIL"

    # Check if account already exists
    if echo "$EXISTING_ACCOUNTS" | grep -qw "$ACCOUNT_NAME"; then
        echo "  -> Already exists. Skipping."
        echo ""
        continue
    fi

    # Create the account (async)
    echo "  -> Creating account..."
    CREATE_STATUS_ID=$(aws organizations create-account \
        --email "$ACCOUNT_EMAIL" \
        --account-name "$ACCOUNT_NAME" \
        --role-name "$CROSS_ACCOUNT_ROLE" \
        --region "$REGION" \
        --query 'CreateAccountStatus.Id' \
        --output text)

    # Poll for completion (max 5 minutes)
    echo "  -> Waiting for account creation (ID: $CREATE_STATUS_ID)..."
    SECONDS_WAITED=0
    MAX_WAIT=300

    while [ $SECONDS_WAITED -lt $MAX_WAIT ]; do
        STATUS=$(aws organizations describe-create-account-status \
            --create-account-request-id "$CREATE_STATUS_ID" \
            --region "$REGION" \
            --query 'CreateAccountStatus.State' \
            --output text)

        if [ "$STATUS" = "SUCCEEDED" ]; then
            ACCOUNT_ID=$(aws organizations describe-create-account-status \
                --create-account-request-id "$CREATE_STATUS_ID" \
                --region "$REGION" \
                --query 'CreateAccountStatus.AccountId' \
                --output text)
            echo "  -> Account created: $ACCOUNT_ID"
            break
        elif [ "$STATUS" = "FAILED" ]; then
            FAILURE_REASON=$(aws organizations describe-create-account-status \
                --create-account-request-id "$CREATE_STATUS_ID" \
                --region "$REGION" \
                --query 'CreateAccountStatus.FailureReason' \
                --output text)
            echo "  -> FAILED: $FAILURE_REASON"
            echo "$N,FAILED,$ACCOUNT_NAME,$ACCOUNT_EMAIL,FAILED:$FAILURE_REASON" >> "$STUDENTS_CSV"
            continue 2
        fi

        sleep 10
        SECONDS_WAITED=$((SECONDS_WAITED + 10))
        echo "  -> Status: $STATUS (${SECONDS_WAITED}s elapsed)"
    done

    if [ $SECONDS_WAITED -ge $MAX_WAIT ]; then
        echo "  -> TIMEOUT waiting for account creation."
        echo "$N,TIMEOUT,$ACCOUNT_NAME,$ACCOUNT_EMAIL,TIMEOUT" >> "$STUDENTS_CSV"
        continue
    fi

    # Move account to the workshop OU
    echo "  -> Moving to workshop OU..."
    aws organizations move-account \
        --account-id "$ACCOUNT_ID" \
        --source-parent-id "$ROOT_ID" \
        --destination-parent-id "$OU_ID" \
        --region "$REGION"
    echo "  -> Moved to OU '$OU_NAME'."

    # Log to CSV
    echo "$N,$ACCOUNT_ID,$ACCOUNT_NAME,$ACCOUNT_EMAIL,ACTIVE" >> "$STUDENTS_CSV"

    echo "  -> Done."
    echo ""
done

echo "==========================================="
echo " Account Creation Complete"
echo "==========================================="
echo ""
echo "Accounts logged to: $STUDENTS_CSV"
echo ""
echo "Next step: ./enable-student-access.sh <student-number>"
echo ""
