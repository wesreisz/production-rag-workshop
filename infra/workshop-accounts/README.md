# Workshop Student Account Provisioning

Automated tooling to create isolated AWS accounts for workshop participants using AWS Organizations.

Each student gets their own AWS account with:

- Scoped permissions via Service Control Policy (only workshop-required services)
- Region lock to `us-east-1`
- `$25/month` budget with email alerts at 50%, 80%, 100%
- CLI access keys and console login credentials

## Prerequisites

- AWS CLI configured with **management account** credentials
- A Gmail address (uses `+` addressing for unique per-student emails)

## Setup Sequence

### 1. Configure

```bash
cp config.env.example config.env
# Edit config.env with your email, region, budget, and password
```

### 2. Create the Organization and SCP

```bash
./setup-org.sh
```

Creates the AWS Organization (if needed), a `workshop-students` OU, and attaches a Service Control Policy that restricts student accounts to required services only.

### 3. Create Student Accounts

```bash
./create-students.sh 1 35    # creates student-01 through student-35
./create-students.sh 5 5     # creates only student-05
```

Each account is created under the Organization and moved into the workshop OU. Progress is logged to `students.csv`.

### 4. Enable Student Access

```bash
./enable-student-access.sh 1    # configure student-01
```

Run once per student. Creates the IAM user, generates credentials, sets up a budget. Credentials are saved to `students/student-NN-credentials.txt`.

## Other Scripts

| Script | Description |
|---|---|
| `list-students.sh` | List all student accounts with budget spend |
| `verify-student.sh <N>` | Test that allowed services work and blocked services are denied |
| `teardown-students.sh <start> <end>` | Delete IAM users and close accounts |

## SCP Summary

The Service Control Policy (`scp-workshop.json`) allows only:

S3, Lambda, Step Functions, EventBridge, SQS, Transcribe, Bedrock, RDS, API Gateway, CloudWatch Logs, Secrets Manager, KMS, IAM, STS, DynamoDB, CloudFormation, CloudTrail, CloudWatch, CloudShell, and limited EC2 networking actions (VPC, subnets, security groups — no instances).

All other services and all regions outside `us-east-1` are denied.
