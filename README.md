# Building a Production-Grade RAG Pipeline

An 8-hour hands-on workshop where participants build an end-to-end video ingestion and retrieval pipeline on AWS. Starting with a video uploaded to S3, the system transcribes audio, chunks text, generates embeddings, stores vectors, and exposes a semantic search API -- all orchestrated by AWS Step Functions and queryable from Cursor IDE via MCP.

**Conference:** Arc of AI (April 13-16, 2026 -- Austin, TX)
**Author:** Wesley Reisz

## Architecture

```
Video Upload ──▶ S3 ──▶ EventBridge ──▶ Step Functions
                                            │
                                            ├── Transcribe (AWS Transcribe)
                                            ├── Chunk (Lambda)
                                            ├── Embed (Bedrock Titan V2 ──▶ Aurora pgvector)
                                            └── Done
                                                    │
                        Question API (API Gateway) ◀┘
                              │
                        MCP Server (Cursor IDE)
```

## Technology Stack

| Component | Service |
|-----------|---------|
| Compute | AWS Lambda (Python 3.11) |
| Orchestration | AWS Step Functions |
| Transcription | AWS Transcribe |
| Embeddings | Amazon Bedrock Titan Text Embeddings V2 |
| Vector Database | Aurora Serverless v2 + pgvector |
| Event Routing | EventBridge (S3 native notifications) |
| Message Queue | Amazon SQS |
| API | API Gateway (REST) |
| IDE Integration | MCP Server (Model Context Protocol) |
| Infrastructure | Terraform |

## Workshop Schedule

| Time | Duration | Topic |
|------|----------|-------|
| 09:00 | 45 min | Introduction & Architecture Overview |
| 09:45 | 45 min | Video Upload & Workflow Trigger |
| 10:45 | 90 min | Transcription with AWS Transcribe |
| 13:15 | 75 min | Chunking & Queue-Based Fan-Out |
| 14:30 | 75 min | Embedding & Vector Storage |
| 16:00 | 75 min | Building the Retrieval / Question Service |
| 17:15 | 60 min | MCP Server & Cursor Integration |
| 18:15 | 30 min | Wrap-Up: Production Concerns & Next Steps |

## Local Prerequisites

Install all of the following before starting the workshop.

| Tool | Minimum Version | Why It's Needed | Install |
|------|----------------|-----------------|---------|
| **Git** | 2.x | Clone the repo, version control | [git-scm.com](https://git-scm.com/) |
| **Python** | 3.11+ | Lambda runtime, migrations, verify scripts. Must include `pip` and `venv`. | [python.org](https://www.python.org/downloads/) |
| **AWS CLI** | v2 | Deploy, invoke, and verify all AWS resources | [AWS CLI install guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) |
| **Terraform** | >= 1.5 | Provision all infrastructure (VPC, Aurora, Lambda, Step Functions, etc.) | [developer.hashicorp.com](https://developer.hashicorp.com/terraform/install) |
| **Docker** | 20+ | Build the `psycopg2` Lambda layer (`scripts/build-psycopg2-layer.sh`) | [docs.docker.com](https://docs.docker.com/get-started/get-docker/) |
| **Cursor IDE** | Latest | AI-assisted development, MCP server integration (free tier is sufficient) | [cursor.com](https://www.cursor.com/) |

### Verify your setup

```bash
git --version          # git version 2.x
python3 --version      # Python 3.11+
pip3 --version         # pip 24+
aws --version          # aws-cli/2.x
terraform --version    # Terraform v1.5+
docker --version       # Docker 20+
```

### AWS account setup

You also need an AWS account with billing enabled (or a provided workshop account). After installing the AWS CLI, configure credentials so that `aws sts get-caller-identity` succeeds. In the AWS Console, navigate to **Amazon Bedrock > Model Access** and request access to `amazon.titan-embed-text-v2:0` and `anthropic.claude-3-haiku`.

---

## Instructor Setup: Student Account Provisioning

The workshop uses AWS Organizations to create isolated, budget-capped accounts for each participant. All billing rolls up to your management account. A Service Control Policy restricts students to only the AWS services needed for the workshop and locks them to `us-east-1`.

### Directory Structure

```
infra/workshop-accounts/
  config.env.example       # Template -- copy to config.env and edit
  scp-workshop.json        # Service Control Policy (service + region restrictions)
  setup-org.sh             # One-time: create Organization, OU, and attach SCP
  create-students.sh       # Create N student accounts
  enable-student-access.sh # Configure IAM user, credentials, and budget per student
  verify-student.sh        # Validate all services work / blocked actions are denied
  list-students.sh         # Show all student accounts with status and budget spend
  teardown-students.sh     # Close student accounts
  budget-template.json     # Budget template used by enable-student-access.sh
```

### Quick Start

**1. Configure**

```bash
cd infra/workshop-accounts
cp config.env.example config.env
# Edit config.env: set EMAIL_BASE to your email address
```

Your email must support `+` addressing (Gmail and Google Workspace do). Each student account gets a unique email like `you+workshop-student-01@gmail.com` -- all mail routes to your inbox.

**2. One-time Organization setup**

Create the AWS Organization from the Console (requires root user login):
- Log in as root at https://console.aws.amazon.com/organizations/
- Click "Create an organization" (all features enabled)

Then enable SCPs and create the workshop OU:

```bash
aws organizations enable-policy-type \
  --root-id $(aws organizations list-roots --query 'Roots[0].Id' --output text) \
  --policy-type SERVICE_CONTROL_POLICY

./setup-org.sh
```

This creates:
- An Organizational Unit for student accounts
- A Service Control Policy that allowlists only workshop services and `us-east-1`
- Attaches the SCP to the OU

**3. Create a student account**

```bash
./create-students.sh 1 1       # creates student-01
```

To create a range: `./create-students.sh 1 35` creates student-01 through student-35.

Note: AWS has a default limit of 4 accounts per Organization. Request a quota increase via AWS Support before scaling to 30+.

**4. Configure the student account**

```bash
./enable-student-access.sh 1
```

This assumes the `OrganizationAccountAccessRole` into the student account and:
- Creates an IAM user `workshop-user` with CLI access keys and a console password
- Attaches `PowerUserAccess` + `IAMFullAccess` (effective permissions are constrained by the SCP)
- Creates a budget with email alerts at 50%, 80%, and 100% of the cap
- Saves all credentials to `students/student-01-credentials.txt`

**5. Verify the account**

Configure a CLI profile for the student, then run the verify script:

```bash
aws configure --profile student-01
# Enter access key, secret key, region us-east-1, output json

./verify-student.sh 1
```

The verify script tests 18 allowed services (S3, Lambda, Bedrock, RDS, etc.) and 6 blocked actions (other regions, EC2 instances, SageMaker, org escape). All tests should pass.

**6. Check status**

```bash
./list-students.sh
```

Shows all student accounts with their status (ACTIVE/SUSPENDED) and current budget spend.

**7. Teardown**

```bash
./teardown-students.sh 1 1     # close student-01
./teardown-students.sh 1 35    # close all
```

Cleans up IAM users and access keys, then closes the accounts. Closed accounts enter SUSPENDED state for 90 days (no charges accrue), then permanently close.

### Service Control Policy

The SCP (`scp-workshop.json`) uses a Deny + NotAction pattern to allowlist only these services:

| Service | Purpose |
|---------|---------|
| S3 | Video/transcript/chunk storage |
| Lambda | All module compute |
| Step Functions | Pipeline orchestration |
| EventBridge | S3 event routing |
| Transcribe | Audio-to-text |
| SQS | Chunk fan-out queue |
| Bedrock | Titan Embeddings + Claude Haiku |
| RDS | Aurora Serverless v2 + pgvector |
| EC2 (networking only) | VPC, subnets, security groups, endpoints |
| API Gateway | Question service REST API |
| CloudWatch Logs | Lambda/service logging |
| Secrets Manager | Database credentials |
| KMS | Encryption |
| IAM / STS | Roles, policies, assume-role |
| DynamoDB | Terraform state locking |

EC2 instance launches (`RunInstances`) are explicitly denied. All actions outside `us-east-1` are denied (except global services like IAM and STS).

### Cost

Estimated cost per student for the full workshop (10 videos at 50 min each, 3-day infrastructure lifetime): **~$18**. See [PRD.md](PRD.md) for detailed cost breakdown and cost-saving strategies.

---

## Project Structure (Target)

```
production-rag/
├── infra/
│   ├── workshop-accounts/    # Student account provisioning (documented above)
│   ├── bootstrap/            # Terraform remote state setup
│   ├── environments/dev/     # Dev environment Terraform
│   └── modules/              # Reusable Terraform modules
├── modules/
│   ├── transcribe-module/    # S3 video ──▶ AWS Transcribe ──▶ transcript JSON
│   ├── chunking-module/      # Transcript ──▶ overlapping text chunks
│   ├── embedding-module/     # Chunks ──▶ Bedrock Titan V2 ──▶ Aurora pgvector
│   ├── question-module/      # Question ──▶ embed ──▶ vector search ──▶ answer
│   └── mcp-server/           # MCP server wrapping the question API
├── samples/                  # Sample audio/video files
├── specs/prompts/            # Spec-driven development prompts per stage
├── PRD.md                    # Full Product Requirements Document
└── README.md                 # This file
```

Each module follows the same internal structure:

```
<name>-module/
├── src/
│   ├── handlers/     # Lambda entry points (thin)
│   ├── services/     # Business logic
│   ├── models/       # Data structures
│   └── utils/        # Helpers
├── tests/
├── specs/features/   # Behavioral specifications
├── requirements.txt
└── dev-requirements.txt
```

## Documentation

- [PRD.md](PRD.md) -- Full Product Requirements Document with architecture, module specs, infrastructure design, cost analysis, and RIPER-5 stage mapping

## Reference

This workshop is adapted from [wesreisz/video-pipeline](https://github.com/wesreisz/video-pipeline) with two key changes:
- **Embeddings:** OpenAI &#8594; Amazon Bedrock Titan Text Embeddings V2
- **Vector DB:** Pinecone &#8594; Aurora Serverless v2 + pgvector
