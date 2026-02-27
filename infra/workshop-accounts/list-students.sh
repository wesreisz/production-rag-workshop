#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/config.env"

echo "==========================================="
echo " Workshop Student Accounts"
echo "==========================================="
echo ""

# ------------------------------------------------------------------
# Get workshop OU ID
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
    echo "OU '$OU_NAME' not found. Run setup-org.sh first."
    exit 1
fi

# ------------------------------------------------------------------
# List accounts in the OU
# ------------------------------------------------------------------
ACCOUNTS=$(aws organizations list-accounts-for-parent \
    --parent-id "$OU_ID" \
    --region "$REGION" \
    --query 'Accounts[].{Id:Id, Name:Name, Email:Email, Status:Status}' \
    --output json)

ACCOUNT_COUNT=$(echo "$ACCOUNTS" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")

if [ "$ACCOUNT_COUNT" = "0" ]; then
    echo "No student accounts found in OU '$OU_NAME'."
    echo ""
    echo "Run: ./create-students.sh 1 1"
    exit 0
fi

printf "%-4s %-14s %-30s %-45s %-12s\n" "#" "Account ID" "Name" "Email" "Status"
printf "%-4s %-14s %-30s %-45s %-12s\n" "---" "--------------" "------------------------------" "---------------------------------------------" "------------"

echo "$ACCOUNTS" | python3 -c "
import sys, json

accounts = json.load(sys.stdin)
accounts.sort(key=lambda a: a['Name'])

for acct in accounts:
    num = acct['Name'].split('-')[-1] if '-' in acct['Name'] else '?'
    print(f\"{num:<4} {acct['Id']:<14} {acct['Name']:<30} {acct['Email']:<45} {acct['Status']:<12}\")
"

echo ""
echo "Total: $ACCOUNT_COUNT account(s)"
echo ""

# ------------------------------------------------------------------
# Budget spend summary (only for ACTIVE accounts)
# ------------------------------------------------------------------
ACTIVE_ACCOUNTS=$(echo "$ACCOUNTS" | python3 -c "
import sys, json
accounts = json.load(sys.stdin)
for acct in accounts:
    if acct['Status'] == 'ACTIVE':
        print(acct['Id'])
")

if [ -n "$ACTIVE_ACCOUNTS" ]; then
    echo "--- Budget Spend ---"
    printf "%-14s %-30s %10s %10s\n" "Account ID" "Budget Name" "Spent" "Limit"
    printf "%-14s %-30s %10s %10s\n" "--------------" "------------------------------" "----------" "----------"

    for ACCT_ID in $ACTIVE_ACCOUNTS; do
        ROLE_ARN="arn:aws:iam::${ACCT_ID}:role/${CROSS_ACCOUNT_ROLE}"
        CREDS=$(aws sts assume-role \
            --role-arn "$ROLE_ARN" \
            --role-session-name "budget-check-${ACCT_ID}" \
            --duration-seconds 900 \
            --query 'Credentials' \
            --output json 2>/dev/null) || {
            printf "%-14s %-30s %10s %10s\n" "$ACCT_ID" "(cannot assume role)" "-" "-"
            continue
        }

        BUDGETS=$(AWS_ACCESS_KEY_ID=$(echo "$CREDS" | python3 -c "import sys,json; print(json.load(sys.stdin)['AccessKeyId'])") \
            AWS_SECRET_ACCESS_KEY=$(echo "$CREDS" | python3 -c "import sys,json; print(json.load(sys.stdin)['SecretAccessKey'])") \
            AWS_SESSION_TOKEN=$(echo "$CREDS" | python3 -c "import sys,json; print(json.load(sys.stdin)['SessionToken'])") \
            aws budgets describe-budgets \
                --account-id "$ACCT_ID" \
                --query 'Budgets[].{Name:BudgetName, Limit:BudgetLimit.Amount, Spent:CalculatedSpend.ActualSpend.Amount}' \
                --output json 2>/dev/null) || BUDGETS="[]"

        BUDGET_COUNT=$(echo "$BUDGETS" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")

        if [ "$BUDGET_COUNT" = "0" ]; then
            printf "%-14s %-30s %10s %10s\n" "$ACCT_ID" "(no budget)" "-" "-"
        else
            echo "$BUDGETS" | python3 -c "
import sys, json
acct_id = '$ACCT_ID'
budgets = json.load(sys.stdin)
for b in budgets:
    spent = b.get('Spent') or '0.00'
    limit = b.get('Limit', '?')
    print(f'{acct_id:<14} {b[\"Name\"]:<30} {\"\$\" + str(spent):>10} {\"\$\" + str(limit):>10}')
"
        fi
    done
    echo ""
fi
