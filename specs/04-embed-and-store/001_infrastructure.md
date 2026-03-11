# Embedding Infrastructure

**Deliverable:** Aurora Serverless v2 is running with pgvector enabled, the `video_chunks` table and HNSW index exist, a Secrets Manager secret holds database credentials, VPC networking is configured with security groups and endpoints, and the `lambda-vpc` Terraform module and psycopg2 Lambda layer are ready for use by the embedding Lambda.

---

## Overview

1. Create the networking Terraform module (default VPC reference, security groups, VPC endpoints)
2. Create the Aurora Serverless v2 Terraform module (cluster, instance, Secrets Manager)
3. Create the lambda-vpc Terraform module (extends existing Lambda module with VPC config and layers)
4. Create a build script for the psycopg2 Lambda layer
5. Wire networking, Aurora, and the psycopg2 layer into the dev environment Terraform
6. Deploy infrastructure and initialize the database schema (pgvector extension, tables, indexes)
7. Verify: Aurora is reachable, pgvector is enabled, `video_chunks` table exists

---

## Prerequisites

- [ ] Stage 3 (Chunking & Fan-Out) is complete and verified
- [ ] AWS CLI configured with credentials that have permissions for VPC, RDS, Secrets Manager, and Lambda
- [ ] Docker installed locally (required for building the psycopg2 Lambda layer)
- [ ] Python 3.11+ with `pip` and `venv` support (required for Alembic migrations)
- [ ] Bedrock model access enabled for `amazon.titan-embed-text-v2:0` in the AWS Console (Amazon Bedrock > Model Access)

---

## Architecture Context

```
Default VPC
│
├── Subnets (default, at least 2 AZs for Aurora multi-AZ requirement)
│
├── Security Groups
│   ├── Lambda SG ──── egress: all traffic allowed, ingress: none
│   ├── Aurora SG ──── ingress: TCP 5432 from Lambda SG + CloudShell SG, egress: all
│   └── CloudShell SG ── egress: all traffic allowed, ingress: none
│
├── CloudShell VPC Access
│   ├── Private Subnet (172.31.100.0/24) with NAT Gateway route
│   ├── NAT Gateway (in public default subnet) + Elastic IP
│   └── Route Table: 0.0.0.0/0 → NAT Gateway
│
├── VPC Endpoints
│   ├── S3 Gateway Endpoint (free, associated with default route tables)
│   ├── Bedrock Runtime Interface Endpoint (com.amazonaws.{region}.bedrock-runtime)
│   └── Secrets Manager Interface Endpoint (com.amazonaws.{region}.secretsmanager)
│
└── Aurora Serverless v2
    ├── Cluster: aurora-postgresql 17.7, serverless v2 (0.5–4 ACU)
    ├── Instance: db.serverless
    ├── DB Subnet Group: default VPC subnets
    └── Secrets Manager: JSON {host, port, dbname, username, password}
```

VPC endpoints allow Lambda functions running inside the VPC to reach S3, Bedrock, and Secrets Manager without a NAT Gateway. The S3 gateway endpoint is free. The Bedrock and Secrets Manager interface endpoints cost ~$0.01/hr each.

---

## Database Schema

The embedding Lambda (Stage 4 Part 2) will insert records into this schema. The schema is managed via **Alembic** migrations, providing version-tracked, repeatable database changes.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE video_chunks (
    id SERIAL PRIMARY KEY,
    chunk_id VARCHAR(255) UNIQUE NOT NULL,
    video_id VARCHAR(255) NOT NULL,
    sequence INTEGER NOT NULL,
    text TEXT NOT NULL,
    embedding vector(256),
    speaker VARCHAR(255),
    title VARCHAR(512),
    start_time FLOAT,
    end_time FLOAT,
    source_s3_key VARCHAR(1024),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_video_chunks_embedding
ON video_chunks USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_video_chunks_video_id ON video_chunks(video_id);
CREATE INDEX idx_video_chunks_speaker ON video_chunks(speaker);
```

| Column | Type | Description |
|--------|------|-------------|
| `id` | `SERIAL` | Auto-incrementing primary key |
| `chunk_id` | `VARCHAR(255) UNIQUE` | `{video_id}-chunk-{NNN}` — unique identifier from chunking stage |
| `video_id` | `VARCHAR(255)` | Video identifier, used for filtering |
| `sequence` | `INTEGER` | 1-based chunk sequence within the video |
| `text` | `TEXT` | Full chunk text content |
| `embedding` | `vector(256)` | 256-dimensional Bedrock Titan V2 embedding |
| `speaker` | `VARCHAR(255)` | Speaker name (nullable, for future metadata) |
| `title` | `VARCHAR(512)` | Video title (nullable, for future metadata) |
| `start_time` | `FLOAT` | Chunk start timestamp in seconds |
| `end_time` | `FLOAT` | Chunk end timestamp in seconds |
| `source_s3_key` | `VARCHAR(1024)` | Original uploaded file S3 key |
| `created_at` | `TIMESTAMP` | Record creation time |
| `updated_at` | `TIMESTAMP` | Record update time |

The HNSW index uses `vector_cosine_ops` for cosine similarity search. Parameters `m=16` and `ef_construction=64` are suitable for datasets under 1M vectors.

Embedding dimension is 256 (workshop default). Bedrock Titan V2 supports 256, 512, or 1024. Lower dimensions mean faster search and less storage at the cost of slightly reduced retrieval quality — acceptable for a workshop.

---

## Resources

### Part A: Networking Terraform Module

Create a reusable Terraform module for VPC networking resources needed by VPC-attached Lambdas and Aurora.

**Directory structure:**

```
infra/modules/networking/
├── main.tf
├── variables.tf
└── outputs.tf
```

**Files to create:**

| File | Purpose |
|------|---------|
| `infra/modules/networking/main.tf` | VPC data sources, security groups, VPC endpoints |
| `infra/modules/networking/variables.tf` | Module input variables |
| `infra/modules/networking/outputs.tf` | Module outputs for consumers |

---

#### main.tf

**Data sources:**

| Resource | Type | Purpose |
|----------|------|---------|
| `aws_vpc.default` | `data` | Reference the default VPC (`default = true`) |
| `aws_subnets.default` | `data` | All subnets in the default VPC (filter by `vpc-id`) |
| `aws_route_tables.default` | `data` | Route tables in the default VPC (for S3 gateway endpoint association) |

**Security groups:**

| Resource | Name | Ingress | Egress |
|----------|------|---------|--------|
| `aws_security_group.lambda` | `${var.project_name}-lambda-sg` | None | All traffic (0.0.0.0/0, all ports, all protocols) |
| `aws_security_group.aurora` | `${var.project_name}-aurora-sg` | TCP 5432 from `aws_security_group.lambda.id` and `aws_security_group.cloudshell.id` | All traffic |
| `aws_security_group.cloudshell` | `${var.project_name}-cloudshell-sg` | None | All traffic (0.0.0.0/0, all ports, all protocols) |

**CloudShell VPC access:**

| Resource | Description |
|----------|-------------|
| `aws_subnet.cloudshell` | Private subnet `172.31.100.0/24` for CloudShell VPC environments |
| `aws_eip.nat` | Elastic IP for the NAT gateway |
| `aws_nat_gateway.this` | NAT gateway in a default public subnet (provides internet to CloudShell) |
| `aws_route_table.cloudshell` | Route table with `0.0.0.0/0 -> nat_gateway` |
| `aws_route_table_association.cloudshell` | Associates the CloudShell subnet with the private route table |

**VPC endpoints:**

| Resource | Service | Type | Notes |
|----------|---------|------|-------|
| `aws_vpc_endpoint.s3` | `com.amazonaws.${var.aws_region}.s3` | `Gateway` | `route_table_ids` = `data.aws_route_tables.default.ids` |
| `aws_vpc_endpoint.bedrock` | `com.amazonaws.${var.aws_region}.bedrock-runtime` | `Interface` | `subnet_ids` = `data.aws_subnets.default.ids`, `security_group_ids` = `[aws_security_group.lambda.id]`, `private_dns_enabled` = `true` |
| `aws_vpc_endpoint.secretsmanager` | `com.amazonaws.${var.aws_region}.secretsmanager` | `Interface` | `subnet_ids` = `data.aws_subnets.default.ids`, `security_group_ids` = `[aws_security_group.lambda.id]`, `private_dns_enabled` = `true` |

All resources are tagged with `var.tags`.

---

#### variables.tf

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `project_name` | `string` | — | Project name prefix for resource naming |
| `aws_region` | `string` | — | AWS region for VPC endpoint service names |
| `tags` | `map(string)` | `{}` | Resource tags |

---

#### outputs.tf

| Output | Value | Description |
|--------|-------|-------------|
| `vpc_id` | `data.aws_vpc.default.id` | Default VPC ID |
| `subnet_ids` | `data.aws_subnets.default.ids` | Default VPC subnet IDs |
| `lambda_security_group_id` | `aws_security_group.lambda.id` | Security group for Lambda functions |
| `aurora_security_group_id` | `aws_security_group.aurora.id` | Security group for Aurora cluster |
| `cloudshell_subnet_id` | `aws_subnet.cloudshell.id` | Private subnet for CloudShell VPC environments |
| `cloudshell_security_group_id` | `aws_security_group.cloudshell.id` | Security group for CloudShell VPC environments |

---

### Part B: Aurora Serverless v2 Terraform Module

Create a reusable Terraform module for the Aurora Serverless v2 PostgreSQL cluster with Secrets Manager integration.

**Directory structure:**

```
infra/modules/aurora-vectordb/
├── main.tf
├── variables.tf
└── outputs.tf
```

**Files to create:**

| File | Purpose |
|------|---------|
| `infra/modules/aurora-vectordb/main.tf` | Aurora cluster, instance, subnet group, Secrets Manager |
| `infra/modules/aurora-vectordb/variables.tf` | Module input variables |
| `infra/modules/aurora-vectordb/outputs.tf` | Module outputs for consumers |

---

#### main.tf

| Resource | Type | Key Settings |
|----------|------|-------------|
| `aws_db_subnet_group.aurora` | Subnet group | `name` = `${var.project_name}-aurora`, `subnet_ids` = `var.subnet_ids` |
| `aws_rds_cluster.this` | Aurora cluster | `cluster_identifier` = `${var.project_name}-vectordb`, `engine` = `aurora-postgresql`, `engine_version` = `17.7`, `database_name` = `var.db_name`, `master_username` = `var.master_username`, `master_password` = `var.master_password`, `db_subnet_group_name` = subnet group, `vpc_security_group_ids` = `[var.security_group_id]`, `skip_final_snapshot` = `true`, `apply_immediately` = `true`, `enable_http_endpoint` = `true` |
| `aws_rds_cluster.this` | Serverless v2 scaling | `serverless_v2_scaling_configuration { min_capacity = 0.5, max_capacity = 4 }` |
| `aws_rds_cluster_instance.this` | Cluster instance | `cluster_identifier` = cluster, `instance_class` = `db.serverless`, `engine` = `aurora-postgresql` |
| `aws_secretsmanager_secret.db` | Secret | `name` = `${var.project_name}-aurora-credentials` |
| `aws_secretsmanager_secret_version.db` | Secret value | JSON: `{host, port, dbname, username, password}` from cluster endpoint and variables |

---

#### variables.tf

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `project_name` | `string` | — | Project name prefix |
| `subnet_ids` | `list(string)` | — | Subnet IDs for DB subnet group |
| `security_group_id` | `string` | — | Aurora security group ID |
| `db_name` | `string` | `"ragdb"` | Database name |
| `master_username` | `string` | `"ragadmin"` | Master username |
| `master_password` | `string` | — | Master password (sensitive) |
| `tags` | `map(string)` | `{}` | Resource tags |

---

#### outputs.tf

| Output | Value | Description |
|--------|-------|-------------|
| `cluster_endpoint` | `aws_rds_cluster.this.endpoint` | Aurora cluster writer endpoint |
| `cluster_port` | `aws_rds_cluster.this.port` | Aurora cluster port (5432) |
| `secret_arn` | `aws_secretsmanager_secret.db.arn` | Secrets Manager secret ARN |
| `cluster_arn` | `aws_rds_cluster.this.arn` | Aurora cluster ARN |
| `db_name` | `var.db_name` | Database name |

---

### Part C: Lambda VPC Terraform Module

Create a VPC-aware Lambda module by extending the existing `infra/modules/lambda/` module with VPC configuration and layer support.

**Directory structure:**

```
infra/modules/lambda-vpc/
├── main.tf
├── variables.tf
└── outputs.tf
```

**Files to create:**

| File | Purpose |
|------|---------|
| `infra/modules/lambda-vpc/main.tf` | Lambda with VPC config and layer support |
| `infra/modules/lambda-vpc/variables.tf` | Module input variables (extends lambda module vars) |
| `infra/modules/lambda-vpc/outputs.tf` | Module outputs (same as lambda module) |

---

#### main.tf

Same as `infra/modules/lambda/main.tf` with these additions to `aws_lambda_function.this`:

```
vpc_config {
  subnet_ids         = var.subnet_ids
  security_group_ids = var.security_group_ids
}

layers = var.layers
```

Add one additional IAM policy attachment:

| Resource | Policy ARN |
|----------|-----------|
| `aws_iam_role_policy_attachment.vpc` | `arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole` |

This grants the Lambda permission to create and manage ENIs in the VPC.

---

#### variables.tf

All variables from `infra/modules/lambda/variables.tf` plus:

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `subnet_ids` | `list(string)` | — | VPC subnet IDs for Lambda |
| `security_group_ids` | `list(string)` | — | Security group IDs for Lambda |
| `layers` | `list(string)` | `[]` | Lambda layer ARNs (e.g. psycopg2) |

---

#### outputs.tf

Same as `infra/modules/lambda/outputs.tf`:

| Output | Value | Description |
|--------|-------|-------------|
| `function_name` | `aws_lambda_function.this.function_name` | Lambda function name |
| `function_arn` | `aws_lambda_function.this.arn` | Lambda function ARN |
| `invoke_arn` | `aws_lambda_function.this.invoke_arn` | Lambda invoke ARN |
| `role_arn` | `aws_iam_role.lambda.arn` | Lambda IAM execution role ARN |

---

### Part D: psycopg2 Lambda Layer

The `psycopg2-binary` PyPI package ships pre-compiled binaries for common platforms, but the wheels do not match the Lambda runtime (Amazon Linux 2, x86_64). A Lambda layer must be built using Docker to compile psycopg2 against the correct libraries.

**Files to create:**

| File | Purpose |
|------|---------|
| `scripts/build-psycopg2-layer.sh` | Docker-based build script for psycopg2 Lambda layer |

---

#### build-psycopg2-layer.sh

The script:

1. Creates a temporary directory
2. Runs a Docker container using `public.ecr.aws/lambda/python:3.11` (matches Lambda runtime)
3. Inside the container: `pip install psycopg2-binary -t /out/python/lib/python3.11/site-packages/`
4. Copies the output to `layers/psycopg2/` in the project root
5. Creates `layers/psycopg2/psycopg2-layer.zip` for use by Terraform

The resulting zip file structure:

```
psycopg2-layer.zip
└── python/
    └── lib/
        └── python3.11/
            └── site-packages/
                └── psycopg2/
                    ├── __init__.py
                    └── ...
```

**Terraform resource** (in `infra/environments/dev/main.tf`):

| Resource | Type | Key Settings |
|----------|------|-------------|
| `aws_lambda_layer_version.psycopg2` | Lambda layer | `layer_name` = `${var.project_name}-psycopg2`, `filename` = layer zip path, `compatible_runtimes` = `["python3.11"]` |

---

### Part E: DB Schema Migrations (Alembic)

Database schema is managed via **Alembic** migrations rather than ad-hoc SQL scripts. This provides version-tracked, repeatable, reversible schema changes — a production best practice.

**Requirements:**

- Initialize an Alembic project in a `migrations/` directory at the project root
- Database URL must be configurable via environment variable (not hardcoded)
- Dependencies: `alembic`, `sqlalchemy`, `psycopg2-binary`, `pgvector`
- Create a wrapper script `scripts/run-migrations.sh` that reads connection details from Terraform outputs and runs migrations

**Initial migration (`001`):**

- Enable the `pgvector` extension
- Create the `video_chunks` table matching the [Database Schema](#database-schema) section above
- Create the HNSW index on the `embedding` column
- Create metadata indexes on `video_id` and `speaker`
- Must include both `upgrade` and `downgrade` functions (reversible)

**Design constraints:**

- Future schema changes (e.g. `videos` metadata table in Stage 5) are added as new migration files — running migrations applies only pending changes
- The `pgvector` Python package provides SQLAlchemy/Alembic integration for the `vector` column type

---

### Part E-2: Automated Schema Migration via Lambda

The manual CloudShell workflow for running Alembic migrations (Part E, Verification Steps 2–4) requires participants to create a VPC environment, install psql, and run commands by hand. This is error-prone in a workshop setting.

To eliminate this friction, a **migration Lambda** runs the schema SQL automatically during `terraform apply`:

**Directory structure:**

```
modules/migration-module/
├── src/
│   ├── __init__.py
│   └── handlers/
│       ├── __init__.py
│       └── run_migrations.py
```

**How it works:**

1. A `module "run_migrations"` deploys a VPC-attached Lambda (same networking, psycopg2 layer, and Secrets Manager access as the embedding Lambda)
2. The handler reads `SECRET_ARN` and `DB_NAME` from environment variables, connects to Aurora, and executes the same schema SQL from Part E — but with `IF NOT EXISTS` guards on every statement for idempotency
3. A `null_resource "run_migrations"` with a `local-exec` provisioner invokes the Lambda via `aws lambda invoke` after both the Lambda and Aurora are deployed
4. The `null_resource` uses `triggers = { migration_hash = filesha256(...) }` on the handler file, so it re-runs only when the migration SQL changes

This means `terraform apply` deploys Aurora **and** initializes the schema in a single step. The Alembic project in `migrations/` and the `scripts/run-migrations.sh` wrapper remain available for ad-hoc use and future schema evolution, but are no longer required for initial setup.

---

### Part F: Wiring in Dev Environment Terraform

Add the networking and Aurora modules to `infra/environments/dev/main.tf`.

**New module calls:**

```
module "networking" {
  source       = "../../modules/networking"
  project_name = var.project_name
  aws_region   = var.aws_region
  tags         = local.common_tags
}

module "aurora_vectordb" {
  source            = "../../modules/aurora-vectordb"
  project_name      = var.project_name
  subnet_ids        = module.networking.subnet_ids
  security_group_id = module.networking.aurora_security_group_id
  master_password   = var.aurora_master_password
  tags              = local.common_tags
}
```

**New variable** (in `infra/environments/dev/variables.tf`):

| Variable | Type | Sensitive | Description |
|----------|------|-----------|-------------|
| `aurora_master_password` | `string` | `true` | Aurora master password. Pass via `TF_VAR_aurora_master_password` or `-var` |

**New psycopg2 layer resource** (in `infra/environments/dev/main.tf`):

```
resource "aws_lambda_layer_version" "psycopg2" {
  layer_name          = "${var.project_name}-psycopg2"
  filename            = "${path.module}/../../../layers/psycopg2/psycopg2-layer.zip"
  compatible_runtimes = ["python3.11"]
  source_code_hash    = filebase64sha256("${path.module}/../../../layers/psycopg2/psycopg2-layer.zip")
}
```

**New outputs** (in `infra/environments/dev/outputs.tf`):

| Output | Value | Description |
|--------|-------|-------------|
| `aurora_cluster_endpoint` | `module.aurora_vectordb.cluster_endpoint` | Aurora writer endpoint |
| `aurora_secret_arn` | `module.aurora_vectordb.secret_arn` | Secrets Manager secret ARN |
| `aurora_db_name` | `module.aurora_vectordb.db_name` | Database name |
| `vpc_id` | `module.networking.vpc_id` | VPC ID |
| `lambda_security_group_id` | `module.networking.lambda_security_group_id` | Lambda security group |
| `cloudshell_subnet_id` | `module.networking.cloudshell_subnet_id` | Private subnet for CloudShell VPC environments |
| `cloudshell_security_group_id` | `module.networking.cloudshell_security_group_id` | Security group for CloudShell VPC environments |

---

## Implementation Checklist

- [ ] 1. Create `infra/modules/networking/variables.tf` with `project_name`, `aws_region`, `tags`
- [ ] 2. Create `infra/modules/networking/main.tf` with default VPC data source, subnets data source, route tables data source, Lambda security group, Aurora security group, S3 gateway endpoint, Bedrock interface endpoint, Secrets Manager interface endpoint
- [ ] 3. Create `infra/modules/networking/outputs.tf` with `vpc_id`, `subnet_ids`, `lambda_security_group_id`, `aurora_security_group_id`
- [ ] 4. Create `infra/modules/aurora-vectordb/variables.tf` with `project_name`, `subnet_ids`, `security_group_id`, `db_name`, `master_username`, `master_password`, `tags`
- [ ] 5. Create `infra/modules/aurora-vectordb/main.tf` with DB subnet group, Aurora cluster (aurora-postgresql 17.7, serverless v2 0.5–4 ACU), cluster instance (db.serverless), Secrets Manager secret and version
- [ ] 6. Create `infra/modules/aurora-vectordb/outputs.tf` with `cluster_endpoint`, `cluster_port`, `secret_arn`, `cluster_arn`, `db_name`
- [ ] 7. Create `infra/modules/lambda-vpc/variables.tf` (all variables from `infra/modules/lambda/variables.tf` plus `subnet_ids`, `security_group_ids`, `layers`)
- [ ] 8. Create `infra/modules/lambda-vpc/main.tf` (copy of `infra/modules/lambda/main.tf` plus `vpc_config` block, `layers` attribute, `AWSLambdaVPCAccessExecutionRole` policy attachment)
- [ ] 9. Create `infra/modules/lambda-vpc/outputs.tf` (same as `infra/modules/lambda/outputs.tf`)
- [ ] 10. Create `scripts/build-psycopg2-layer.sh` (Docker-based build for psycopg2 Lambda layer)
- [ ] 11. Run `scripts/build-psycopg2-layer.sh` to produce `layers/psycopg2/psycopg2-layer.zip`
- [ ] 12. Add `aurora_master_password` variable to `infra/environments/dev/variables.tf`
- [ ] 13. Add `module "networking"` to `infra/environments/dev/main.tf`
- [ ] 14. Add `module "aurora_vectordb"` to `infra/environments/dev/main.tf`
- [ ] 15. Add `aws_lambda_layer_version.psycopg2` resource to `infra/environments/dev/main.tf`
- [ ] 16. Add new outputs to `infra/environments/dev/outputs.tf` (`aurora_cluster_endpoint`, `aurora_secret_arn`, `aurora_db_name`, `vpc_id`, `lambda_security_group_id`)
- [ ] 17. Initialize Alembic project in `migrations/` directory with dependencies and environment-variable-based DB URL
- [ ] 18. Create initial migration (`001`) for pgvector extension, `video_chunks` table, and indexes (reversible)
- [ ] 19. Create `scripts/run-migrations.sh` wrapper that reads connection details from Terraform outputs
- [ ] 20. Run `terraform init && terraform apply` in `infra/environments/dev/`
- [ ] 21. Install migration dependencies and run migrations against Aurora
- [ ] 22. Verify: pgvector extension is enabled
- [ ] 23. Verify: `video_chunks` table and indexes exist
- [ ] 24. Verify: Alembic version is tracked in the database

---

## Verification

### Step 1: Deploy infrastructure

```bash
cd infra/environments/dev
terraform init
terraform plan  -var="aurora_master_password=YourSecurePassword123!"
terraform apply -var="aurora_master_password=YourSecurePassword123!"
```

### Step 2: Create CloudShell VPC environment

Aurora is only accessible from within the VPC. Create a CloudShell VPC environment in the AWS Console:

1. Open CloudShell, click the **+** icon, select **Create VPC environment**
2. Select the default VPC, the `production-rag-cloudshell-subnet` subnet, and the `production-rag-cloudshell-sg` security group
3. Use `terraform output cloudshell_subnet_id` and `terraform output cloudshell_security_group_id` for the exact IDs

### Step 3: Run Alembic migrations (from CloudShell VPC)

In the CloudShell VPC environment, install psql and run migrations:

```bash
sudo yum install -y postgresql15
ENDPOINT="<aurora_cluster_endpoint from terraform output>"
PGPASSWORD=YourSecurePassword123! alembic upgrade head
```

### Step 4: Verify with psql (from CloudShell VPC)

In the CloudShell VPC environment, verify the schema:

```bash
PGPASSWORD=YourSecurePassword123! psql -h "$ENDPOINT" -U ragadmin -d ragdb -c "SELECT extname FROM pg_extension WHERE extname = 'vector';"
PGPASSWORD=YourSecurePassword123! psql -h "$ENDPOINT" -U ragadmin -d ragdb -c "\dt video_chunks"
PGPASSWORD=YourSecurePassword123! psql -h "$ENDPOINT" -U ragadmin -d ragdb -c "\di idx_video_chunks_*"
PGPASSWORD=YourSecurePassword123! psql -h "$ENDPOINT" -U ragadmin -d ragdb -c "SELECT * FROM alembic_version;"
```

### Step 5: Check result

All four psql commands should return results confirming the pgvector extension, video_chunks table, indexes, and Alembic version `001`.

---

## Success Criteria

| Criterion | How to verify |
|-----------|---------------|
| Networking module creates security groups | `aws ec2 describe-security-groups` shows `production-rag-lambda-sg` and `production-rag-aurora-sg` |
| Aurora SG allows Lambda SG on 5432 | Aurora SG ingress rule references Lambda SG ID on port 5432 |
| S3 gateway endpoint exists | `aws ec2 describe-vpc-endpoints` shows S3 gateway in available state |
| Bedrock interface endpoint exists | Endpoint for `bedrock-runtime` in available state with private DNS |
| Secrets Manager interface endpoint exists | Endpoint for `secretsmanager` in available state with private DNS |
| Aurora cluster is running | `aws rds describe-db-clusters` shows status `available` |
| Aurora is Serverless v2 | Instance class is `db.serverless`, scaling config shows min 0.5 / max 4 ACU |
| Secrets Manager has credentials | Secret contains JSON with host, port, dbname, username, password |
| Secret host matches Aurora endpoint | `host` value in secret equals `terraform output aurora_cluster_endpoint` |
| Alembic migration applied | `SELECT * FROM alembic_version` returns version `001` |
| pgvector extension enabled | `SELECT * FROM pg_extension WHERE extname = 'vector'` returns one row |
| video_chunks table exists | `\dt video_chunks` shows the table |
| HNSW index exists | `\di idx_video_chunks_embedding` shows the index |
| Metadata indexes exist | `\di idx_video_chunks_video_id` and `\di idx_video_chunks_speaker` show indexes |
| Embedding column is vector(256) | `SELECT column_name, udt_name FROM information_schema.columns WHERE table_name = 'video_chunks' AND column_name = 'embedding'` shows `vector` |
| Migration is reversible | Running the downgrade drops tables and extension; running upgrade again recreates them |
| Migration files exist | `migrations/versions/001_initial_schema.py` exists with `upgrade` and `downgrade` |
| lambda-vpc module exists | `infra/modules/lambda-vpc/` has main.tf, variables.tf, outputs.tf |
| psycopg2 layer deployed | `aws lambda list-layer-versions --layer-name production-rag-psycopg2` returns a valid ARN |
| NAT gateway available | `aws ec2 describe-nat-gateways` shows NAT in `available` state |
| CloudShell SG exists | `aws ec2 describe-security-groups` shows `production-rag-cloudshell-sg` |
| CloudShell VPC env connects to Aurora | `psql -h ENDPOINT -U ragadmin -d ragdb -c "SELECT 1"` succeeds from CloudShell VPC environment |
| Terraform plan is clean | `terraform plan` shows no pending changes after apply |
