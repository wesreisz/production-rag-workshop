#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/config.env"

# ------------------------------------------------------------------
# Usage
# ------------------------------------------------------------------
if [ $# -lt 1 ]; then
    echo "Usage: $0 <student_number>"
    echo ""
    echo "Examples:"
    echo "  $0 1       # Configure student-01 account"
    echo "  $0 15      # Configure student-15 account"
    exit 1
fi

STUDENT_NUM=$1
PADDED=$(printf '%02d' "$STUDENT_NUM")
ACCOUNT_NAME="${STUDENT_ACCOUNT_PREFIX}-${PADDED}"

echo "==========================================="
echo " Enable Access: Student $PADDED"
echo "==========================================="
echo ""

# ------------------------------------------------------------------
# Look up account ID from CSV or Organizations
# ------------------------------------------------------------------
ACCOUNT_ID=""

if [ -f "$STUDENTS_CSV" ]; then
    ACCOUNT_ID=$(grep "^${STUDENT_NUM}," "$STUDENTS_CSV" | cut -d',' -f2 | head -1)
fi

if [ -z "$ACCOUNT_ID" ] || [ "$ACCOUNT_ID" = "FAILED" ] || [ "$ACCOUNT_ID" = "TIMEOUT" ]; then
    ACCOUNT_ID=$(aws organizations list-accounts \
        --region "$REGION" \
        --query "Accounts[?Name=='${ACCOUNT_NAME}' && Status=='ACTIVE'].Id" \
        --output text)
fi

if [ -z "$ACCOUNT_ID" ] || [ "$ACCOUNT_ID" = "None" ]; then
    echo "ERROR: Could not find active account '$ACCOUNT_NAME'."
    echo "       Run create-students.sh $STUDENT_NUM $STUDENT_NUM first."
    exit 1
fi

echo "Account ID: $ACCOUNT_ID"
echo "Account:    $ACCOUNT_NAME"
echo ""

# ------------------------------------------------------------------
# Assume role into the student account
# ------------------------------------------------------------------
echo "[1/5] Assuming role into student account..."

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${CROSS_ACCOUNT_ROLE}"

CREDS=$(aws sts assume-role \
    --role-arn "$ROLE_ARN" \
    --role-session-name "workshop-setup-${PADDED}" \
    --duration-seconds 3600 \
    --query 'Credentials' \
    --output json)

export AWS_ACCESS_KEY_ID=$(echo "$CREDS" | python3 -c "import sys,json; print(json.load(sys.stdin)['AccessKeyId'])")
export AWS_SECRET_ACCESS_KEY=$(echo "$CREDS" | python3 -c "import sys,json; print(json.load(sys.stdin)['SecretAccessKey'])")
export AWS_SESSION_TOKEN=$(echo "$CREDS" | python3 -c "import sys,json; print(json.load(sys.stdin)['SessionToken'])")

CALLER=$(aws sts get-caller-identity --query 'Arn' --output text)
echo "  -> Assumed role: $CALLER"
echo ""

# ------------------------------------------------------------------
# Create IAM user for the student
# ------------------------------------------------------------------
echo "[2/5] Creating IAM user '$STUDENT_IAM_USER'..."

if aws iam get-user --user-name "$STUDENT_IAM_USER" 2>/dev/null; then
    echo "  -> User already exists. Skipping creation."
else
    aws iam create-user --user-name "$STUDENT_IAM_USER"
    echo "  -> User created."
fi

# Attach PowerUserAccess (SCP constrains effective permissions)
POLICY_ATTACHED=$(aws iam list-attached-user-policies \
    --user-name "$STUDENT_IAM_USER" \
    --query "AttachedPolicies[?PolicyArn=='arn:aws:iam::aws:policy/PowerUserAccess'].PolicyArn" \
    --output text)

if [ -z "$POLICY_ATTACHED" ] || [ "$POLICY_ATTACHED" = "None" ]; then
    aws iam attach-user-policy \
        --user-name "$STUDENT_IAM_USER" \
        --policy-arn "arn:aws:iam::aws:policy/PowerUserAccess"
    echo "  -> PowerUserAccess policy attached."
fi

# Also need IAMFullAccess for Terraform to create roles
IAM_POLICY_ATTACHED=$(aws iam list-attached-user-policies \
    --user-name "$STUDENT_IAM_USER" \
    --query "AttachedPolicies[?PolicyArn=='arn:aws:iam::aws:policy/IAMFullAccess'].PolicyArn" \
    --output text)

if [ -z "$IAM_POLICY_ATTACHED" ] || [ "$IAM_POLICY_ATTACHED" = "None" ]; then
    aws iam attach-user-policy \
        --user-name "$STUDENT_IAM_USER" \
        --policy-arn "arn:aws:iam::aws:policy/IAMFullAccess"
    echo "  -> IAMFullAccess policy attached."
fi

echo ""

# ------------------------------------------------------------------
# Generate access keys
# ------------------------------------------------------------------
echo "[3/5] Generating credentials..."

mkdir -p "$STUDENTS_DIR"
CRED_FILE="${STUDENTS_DIR}/student-${PADDED}-credentials.txt"

# Delete existing access keys (max 2 per user)
EXISTING_KEYS=$(aws iam list-access-keys \
    --user-name "$STUDENT_IAM_USER" \
    --query 'AccessKeyMetadata[].AccessKeyId' \
    --output text)

for KEY_ID in $EXISTING_KEYS; do
    aws iam delete-access-key \
        --user-name "$STUDENT_IAM_USER" \
        --access-key-id "$KEY_ID"
    echo "  -> Deleted old access key: $KEY_ID"
done

# Create new access key
NEW_KEY=$(aws iam create-access-key \
    --user-name "$STUDENT_IAM_USER" \
    --query 'AccessKey' \
    --output json)

STUDENT_ACCESS_KEY=$(echo "$NEW_KEY" | python3 -c "import sys,json; print(json.load(sys.stdin)['AccessKeyId'])")
STUDENT_SECRET_KEY=$(echo "$NEW_KEY" | python3 -c "import sys,json; print(json.load(sys.stdin)['SecretAccessKey'])")

# Create/reset console password
aws iam create-login-profile \
    --user-name "$STUDENT_IAM_USER" \
    --password "$STUDENT_DEFAULT_PASSWORD" \
    --password-reset-required 2>/dev/null \
|| aws iam update-login-profile \
    --user-name "$STUDENT_IAM_USER" \
    --password "$STUDENT_DEFAULT_PASSWORD" \
    --password-reset-required

CONSOLE_URL="https://${ACCOUNT_ID}.signin.aws.amazon.com/console"

cat > "$CRED_FILE" <<CREDENTIALS
=========================================
 Workshop Credentials: Student $PADDED
=========================================

AWS Console Login:
  URL:      $CONSOLE_URL
  Username: $STUDENT_IAM_USER
  Password: $STUDENT_DEFAULT_PASSWORD
  (You will be asked to change your password on first login)

AWS CLI Credentials:
  Region:          $REGION
  Access Key ID:   $STUDENT_ACCESS_KEY
  Secret Key:      $STUDENT_SECRET_KEY

To configure the CLI:
  aws configure
  # Enter the Access Key ID and Secret Key above
  # Region: $REGION
  # Output format: json

Account ID: $ACCOUNT_ID
=========================================
CREDENTIALS

echo "  -> Credentials saved to: $CRED_FILE"
echo ""

# ------------------------------------------------------------------
# Create AWS Budget
# ------------------------------------------------------------------
echo "[4/5] Creating budget..."

BUDGET_NAME="workshop-budget-student-${PADDED}"
START_DATE=$(date -u +"%Y-%m-01T00:00:00.000Z")

BUDGET_JSON=$(cat "$SCRIPT_DIR/budget-template.json" \
    | sed "s/__BUDGET_NAME__/${BUDGET_NAME}/g" \
    | sed "s/__BUDGET_LIMIT__/${BUDGET_LIMIT}/g" \
    | sed "s|__START_DATE__|${START_DATE}|g")

NOTIFICATIONS_JSON='[
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 50,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [
      {
        "SubscriptionType": "EMAIL",
        "Address": "'"$NOTIFICATION_EMAIL"'"
      }
    ]
  },
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 80,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [
      {
        "SubscriptionType": "EMAIL",
        "Address": "'"$NOTIFICATION_EMAIL"'"
      }
    ]
  },
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 100,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [
      {
        "SubscriptionType": "EMAIL",
        "Address": "'"$NOTIFICATION_EMAIL"'"
      }
    ]
  }
]'

# Delete existing budget if present, then create fresh
aws budgets delete-budget \
    --account-id "$ACCOUNT_ID" \
    --budget-name "$BUDGET_NAME" 2>/dev/null || true

aws budgets create-budget \
    --account-id "$ACCOUNT_ID" \
    --budget "$BUDGET_JSON" \
    --notifications-with-subscribers "$NOTIFICATIONS_JSON"

echo "  -> Budget '$BUDGET_NAME' created (\$${BUDGET_LIMIT} cap)."
echo "  -> Alerts at 50%, 80%, 100% -> $NOTIFICATION_EMAIL"
echo ""

# ------------------------------------------------------------------
# Bedrock model access note
# ------------------------------------------------------------------
echo "[5/5] Bedrock model access..."
echo ""
echo "  !! MANUAL STEP REQUIRED !!"
echo "  Bedrock foundation model access must be enabled via the AWS Console."
echo "  1. Log in to: $CONSOLE_URL"
echo "     (or assume role from management account)"
echo "  2. Go to: Amazon Bedrock > Model access (us-east-1)"
echo "  3. Request access to:"
echo "     - Amazon Titan Text Embeddings V2"
echo "     - Anthropic Claude 3 Haiku"
echo "  4. Wait for approval (usually instant for these models)"
echo ""

# ------------------------------------------------------------------
# Clear assumed-role credentials
# ------------------------------------------------------------------
unset AWS_ACCESS_KEY_ID
unset AWS_SECRET_ACCESS_KEY
unset AWS_SESSION_TOKEN

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
echo "==========================================="
echo " Student $PADDED Setup Complete"
echo "==========================================="
echo ""
echo "  Account ID:    $ACCOUNT_ID"
echo "  Account Name:  $ACCOUNT_NAME"
echo "  Console URL:   $CONSOLE_URL"
echo "  Credentials:   $CRED_FILE"
echo "  Budget:        \$${BUDGET_LIMIT}/month"
echo ""
echo "  Remaining manual step: Enable Bedrock model access (see above)"
echo ""
