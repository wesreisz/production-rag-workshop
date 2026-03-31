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
- [ ] Bedrock `amazon.titan-embed-text-v2:0` is available (enabled by default)

---

## Architecture Context

```
Default VPC
│
├── Subnets (default, at least 2 AZs for Aurora multi-AZ requirement)
│
├── Security Groups
│   ├── Lambda SG ──── egress: all traffic allowed, ingress: none
│   └── Aurora SG ──── ingress: TCP 5432 from Lambda SG, egress: all
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

VPC endpoints allow Lambda functions running inside the VPC to reach S3, Bedrock, and Secrets Manager without a NAT Gateway. The S3 gateway endpoint is free. The Bedrock and Secrets Manager interface endpoints cost ~$0.01/hr per AZ each. To minimize cost for the workshop, both interface endpoints are pinned to a single AZ (one subnet) instead of all default subnets.

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
| `aws_security_group.aurora` | `${var.project_name}-aurora-sg` | TCP 5432 from `aws_security_group.lambda.id` | All traffic |

**VPC endpoints:**

| Resource | Service | Type | Notes |
|----------|---------|------|-------|
| `aws_vpc_endpoint.s3` | `com.amazonaws.${var.aws_region}.s3` | `Gateway` | `route_table_ids` = `data.aws_route_tables.default.ids` |
| `aws_vpc_endpoint.bedrock` | `com.amazonaws.${var.aws_region}.bedrock-runtime` | `Interface` | `subnet_ids` = `[tolist(data.aws_subnets.default.ids)[0]]` (single AZ), `security_group_ids` = `[aws_security_group.lambda.id]`, `private_dns_enabled` = `true` |
| `aws_vpc_endpoint.secretsmanager` | `com.amazonaws.${var.aws_region}.secretsmanager` | `Interface` | `subnet_ids` = `[tolist(data.aws_subnets.default.ids)[0]]` (single AZ), `security_group_ids` = `[aws_security_group.lambda.id]`, `private_dns_enabled` = `true` |

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

### Part E: DB Schema Migrations (Alembic via Lambda)

Database schema is managed via **Alembic** migrations, providing version-tracked, repeatable, reversible schema changes. A migration Lambda runs `alembic upgrade head` automatically during `terraform apply`, so Alembic is the single source of truth and no manual migration step is needed.

**Directory structure:**

```
modules/migration-module/
├── migrations/
│   ├── alembic.ini
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial_schema.py
├── src/
│   ├── __init__.py
│   └── handlers/
│       ├── __init__.py
│       └── run_migrations.py
└── requirements.txt          # alembic, sqlalchemy (bundled into Lambda zip)
```

**Initial migration (`001`):**

- Enable the `pgvector` extension
- Create the `video_chunks` table matching the [Database Schema](#database-schema) section above
- Create the HNSW index on the `embedding` column
- Create metadata indexes on `video_id` and `speaker`
- Must include both `upgrade` and `downgrade` functions (reversible)

**How it works:**

1. A `null_resource "build_migration_deps"` runs `scripts/build-migration-module.sh` to pip-install `alembic` and `sqlalchemy` into the module directory (Docker-based, linux/amd64). This runs automatically during `terraform apply`, triggered by migration file hashes.
2. A `module "run_migrations"` deploys a VPC-attached Lambda (same networking, psycopg2 layer, and Secrets Manager access as the embedding Lambda). The Lambda zip includes the Alembic project and its Python dependencies.
3. The handler reads `SECRET_ARN` and `DB_NAME` from environment variables, builds a SQLAlchemy engine, and calls `alembic.command.upgrade(config, "head")` programmatically — running all pending Alembic migrations.
4. A `null_resource "run_migrations"` with a `local-exec` provisioner invokes the Lambda via `aws lambda invoke` after both the Lambda and Aurora are deployed. It triggers when the handler file or any Alembic version file changes.

This means `terraform apply` builds deps, deploys the Lambda, and runs migrations in a single step.

**env.py dual-mode design:**

The `env.py` supports two execution paths:
- **Lambda path:** Receives a pre-built SQLAlchemy connection via `config.attributes["connection"]` (set by the handler)
- **Local path:** Falls back to `engine_from_config` using a `DATABASE_URL` environment variable, for use with `scripts/run-migrations.sh`

**Local development script:**

`scripts/run-migrations.sh` reads connection details from Terraform outputs and runs `alembic upgrade head` locally. This is useful for ad-hoc migration work but is not required for deployment.

**Design constraints:**

- Future schema changes are added as new Alembic version files — running migrations applies only pending changes
- Adding a new version file automatically triggers the Lambda on the next `terraform apply` (the Terraform trigger hashes all `.py` files in `migrations/versions/`)

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

---

## Implementation Checklist

- [ ] 1. Create `infra/modules/networking/variables.tf` with `project_name`, `aws_region`, `tags`
- [ ] 2. Create `infra/modules/networking/main.tf` with default VPC data source, subnets data source, route tables data source, Lambda security group, Aurora security group, S3 gateway endpoint, Bedrock interface endpoint (single AZ), Secrets Manager interface endpoint (single AZ)
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
- [ ] 17. Create `modules/migration-module/migrations/` with `alembic.ini`, `env.py` (dual-mode: Lambda connection or `DATABASE_URL` fallback), and `script.py.mako`
- [ ] 18. Create initial migration (`modules/migration-module/migrations/versions/001_initial_schema.py`) for pgvector extension, `video_chunks` table, and indexes (reversible)
- [ ] 19. Create `modules/migration-module/src/handlers/run_migrations.py` that calls `alembic.command.upgrade(config, "head")` using SecretsManager credentials
- [ ] 20. Create `modules/migration-module/requirements.txt` with `alembic` and `sqlalchemy`
- [ ] 21. Create `scripts/build-migration-module.sh` (Docker-based pip install of alembic + sqlalchemy into the module directory)
- [ ] 22. Create `scripts/run-migrations.sh` wrapper that reads connection details from Terraform outputs for local use
- [ ] 23. Add `null_resource "build_migration_deps"` to `infra/environments/dev/main.tf` (auto-runs the build script, triggered by migration file hashes)
- [ ] 24. Add `module "run_migrations"` with `depends_on = [null_resource.build_migration_deps]` to `infra/environments/dev/main.tf`
- [ ] 25. Add `null_resource "run_migrations"` to `infra/environments/dev/main.tf` (triggers on handler hash + versions hash)
- [ ] 26. Run `terraform init && terraform apply` in `infra/environments/dev/`
- [ ] 27. Verify: pgvector extension is enabled
- [ ] 28. Verify: `video_chunks` table and indexes exist
- [ ] 29. Verify: Alembic version is tracked in the database

---

## Verification

### Step 1: Deploy infrastructure

```bash
cd infra/environments/dev
terraform init
terraform plan  -var="aurora_master_password=YourSecurePassword123!"
terraform apply -var="aurora_master_password=YourSecurePassword123!"
```

### Step 2: Verify schema via RDS Query Editor

Aurora is only accessible from within the VPC. Use the **RDS Query Editor** in the AWS Console to verify the schema:

1. Open the RDS Console, select the `production-rag-vectordb` cluster
2. Click **Query** to open the Query Editor
3. Connect using the Secrets Manager secret (`production-rag-aurora-credentials`)
4. Run these verification queries:

```sql
SELECT extname FROM pg_extension WHERE extname = 'vector';
SELECT table_name FROM information_schema.tables WHERE table_name = 'video_chunks';
SELECT indexname FROM pg_indexes WHERE tablename = 'video_chunks';
```

All queries should return results confirming the pgvector extension, video_chunks table, and indexes.

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
| Migration files exist | `modules/migration-module/migrations/versions/001_initial_schema.py` exists with `upgrade` and `downgrade` |
| lambda-vpc module exists | `infra/modules/lambda-vpc/` has main.tf, variables.tf, outputs.tf |
| psycopg2 layer deployed | `aws lambda list-layer-versions --layer-name production-rag-psycopg2` returns a valid ARN |
| Terraform plan is clean | `terraform plan` shows no pending changes after apply |
