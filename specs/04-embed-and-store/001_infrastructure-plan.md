# Embedding Infrastructure — Implementation Plan

**Goal:** Create all networking, Aurora, lambda-vpc Terraform modules, psycopg2 layer, migration module with Alembic, and wire everything into the dev environment so `terraform apply` deploys Aurora Serverless v2 with pgvector, the `video_chunks` table, and all supporting infrastructure.

---

## New Files (20 files)

| # | File | Purpose |
|---|------|---------|
| 1 | `infra/modules/networking/variables.tf` | Input vars: project_name, aws_region, tags |
| 2 | `infra/modules/networking/main.tf` | Default VPC data sources, 2 security groups, 3 VPC endpoints |
| 3 | `infra/modules/networking/outputs.tf` | vpc_id, subnet_ids, lambda_security_group_id, aurora_security_group_id |
| 4 | `infra/modules/aurora-vectordb/variables.tf` | Input vars: project_name, subnet_ids, security_group_id, db_name, master_username, master_password, tags |
| 5 | `infra/modules/aurora-vectordb/main.tf` | Subnet group, Aurora cluster (17.7, serverless v2), instance, Secrets Manager secret+version |
| 6 | `infra/modules/aurora-vectordb/outputs.tf` | cluster_endpoint, cluster_port, secret_arn, cluster_arn, db_name |
| 7 | `infra/modules/lambda-vpc/variables.tf` | All vars from lambda module + subnet_ids, security_group_ids, layers |
| 8 | `infra/modules/lambda-vpc/main.tf` | Copy of lambda/main.tf + vpc_config block, layers attribute, VPCAccessExecutionRole attachment |
| 9 | `infra/modules/lambda-vpc/outputs.tf` | Same 4 outputs as lambda module (function_name, function_arn, invoke_arn, role_arn) |
| 10 | `scripts/build-psycopg2-layer.sh` | Builds psycopg2 Lambda layer zip (Docker optional, linux/amd64) |
| 11 | `modules/migration-module/requirements.txt` | alembic, sqlalchemy |
| 12 | `modules/migration-module/src/__init__.py` | Empty init |
| 13 | `modules/migration-module/src/handlers/__init__.py` | Empty init |
| 14 | `modules/migration-module/src/handlers/run_migrations.py` | Lambda handler: reads secret, builds engine, runs alembic upgrade head |
| 15 | `modules/migration-module/migrations/alembic.ini` | Alembic config, script_location = migrations dir |
| 16 | `modules/migration-module/migrations/env.py` | Dual-mode: Lambda connection or DATABASE_URL fallback |
| 17 | `modules/migration-module/migrations/script.py.mako` | Standard Alembic migration template |
| 18 | `modules/migration-module/migrations/versions/001_initial_schema.py` | pgvector extension, video_chunks table, HNSW + metadata indexes (reversible) |
| 19 | `scripts/build-migration-module.sh` | Installs alembic+sqlalchemy into migration-module dir (Docker optional) |
| 20 | `scripts/run-migrations.sh` | Local wrapper: reads TF outputs, sets DATABASE_URL, runs alembic |

## Files to Modify (3 files)

| File | Changes |
|------|---------|
| `infra/environments/dev/variables.tf` | Add `aurora_master_password` variable (sensitive) |
| `infra/environments/dev/main.tf` | Add networking module, aurora_vectordb module, psycopg2 layer resource, migration build null_resource, run_migrations Lambda module, run_migrations invoke null_resource |
| `infra/environments/dev/outputs.tf` | Add 5 new outputs: aurora_cluster_endpoint, aurora_secret_arn, aurora_db_name, vpc_id, lambda_security_group_id |

---

## Architecture Decisions

**1. lambda-vpc is a full copy, not a wrapper.** The spec says "Same as `infra/modules/lambda/main.tf` with these additions." Copying is simpler than composition/inheritance in Terraform. Keeps `aws_iam_role.this` naming consistent with base module.

**2. Docker-optional build scripts.** Both `build-psycopg2-layer.sh` and `build-migration-module.sh` check if Docker is available. If yes, use `public.ecr.aws/lambda/python:3.11` with `--platform linux/amd64` to match Lambda runtime. If no Docker, use direct `pip install` with `--platform manylinux2014_x86_64 --only-binary=:all:` (works because we're on Linux x86_64).

**3. Migration deps installed into module directory root.** `build-migration-module.sh` pip-installs alembic+sqlalchemy directly into `modules/migration-module/` so they're at the zip root alongside `src/` and `migrations/`. Python can import them at the same level.

**4. Migration Lambda IAM.** Only needs `secretsmanager:GetSecretValue` on the Aurora secret ARN. Database access is via TCP through the VPC (no Data API permissions needed). VPC ENI management comes from `AWSLambdaVPCAccessExecutionRole` (built into lambda-vpc module).

**5. null_resource triggers.** `build_migration_deps` triggers on hash of `requirements.txt`. `run_migrations` triggers on hash of handler file + `filemd5` of all version `.py` files. This ensures `terraform apply` re-invokes the Lambda whenever migrations change.

**6. Alembic env.py dual-mode.** Lambda path: handler passes a live SQLAlchemy connection via `config.attributes["connection"]`. Local path: falls back to `DATABASE_URL` env var for `scripts/run-migrations.sh`.

---

## Detailed Per-File Descriptions

### Part A: Networking Module

**`infra/modules/networking/variables.tf`**
- `project_name` (string, required) — prefix for resource names
- `aws_region` (string, required) — AWS region for endpoint service names
- `tags` (map(string), default `{}`) — resource tags

**`infra/modules/networking/main.tf`**
- Data source `aws_vpc.default` — filter `default = true`
- Data source `aws_subnets.default` — filter by `vpc-id` = default VPC id
- Data source `aws_route_tables.default` — filter by `vpc-id` = default VPC id
- `aws_security_group.lambda` — name `${var.project_name}-lambda-sg`, VPC = default, no ingress, egress all traffic (cidr `0.0.0.0/0`, protocol `-1`, from/to port `0`), tagged
- `aws_security_group.aurora` — name `${var.project_name}-aurora-sg`, VPC = default, ingress TCP 5432 from lambda SG id, egress all traffic, tagged
- `aws_vpc_endpoint.s3` — Gateway type, service `com.amazonaws.${var.aws_region}.s3`, vpc_id = default VPC, route_table_ids = `data.aws_route_tables.default.ids`, tagged
- `aws_vpc_endpoint.bedrock` — Interface type, service `com.amazonaws.${var.aws_region}.bedrock-runtime`, vpc_id = default VPC, subnet_ids = `[tolist(data.aws_subnets.default.ids)[0]]` (single AZ), security_group_ids = `[aws_security_group.lambda.id]`, private_dns_enabled = true, tagged
- `aws_vpc_endpoint.secretsmanager` — Interface type, service `com.amazonaws.${var.aws_region}.secretsmanager`, vpc_id = default VPC, subnet_ids = `[tolist(data.aws_subnets.default.ids)[0]]` (single AZ), security_group_ids = `[aws_security_group.lambda.id]`, private_dns_enabled = true, tagged

**`infra/modules/networking/outputs.tf`**
- `vpc_id` = `data.aws_vpc.default.id`
- `subnet_ids` = `data.aws_subnets.default.ids`
- `lambda_security_group_id` = `aws_security_group.lambda.id`
- `aurora_security_group_id` = `aws_security_group.aurora.id`

---

### Part B: Aurora Vectordb Module

**`infra/modules/aurora-vectordb/variables.tf`**
- `project_name` (string, required)
- `subnet_ids` (list(string), required)
- `security_group_id` (string, required)
- `db_name` (string, default `"ragdb"`)
- `master_username` (string, default `"ragadmin"`)
- `master_password` (string, required, sensitive)
- `tags` (map(string), default `{}`)

**`infra/modules/aurora-vectordb/main.tf`**
- `aws_db_subnet_group.aurora` — name `${var.project_name}-aurora`, subnet_ids from var
- `aws_rds_cluster.this` — cluster_identifier `${var.project_name}-vectordb`, engine `aurora-postgresql`, engine_version `17.7`, database_name from var, master_username from var, master_password from var, db_subnet_group_name from subnet group, vpc_security_group_ids `[var.security_group_id]`, skip_final_snapshot `true`, apply_immediately `true`, enable_http_endpoint `true`, serverlessv2_scaling_configuration block with min_capacity 0.5 and max_capacity 4, tagged
- `aws_rds_cluster_instance.this` — identifier `${var.project_name}-vectordb-instance`, cluster_identifier from cluster, instance_class `db.serverless`, engine `aurora-postgresql`, tagged
- `aws_secretsmanager_secret.db` — name `${var.project_name}-aurora-credentials`, tagged
- `aws_secretsmanager_secret_version.db` — secret_id from secret, secret_string = JSON of `{host: cluster endpoint, port: "5432", dbname: var.db_name, username: var.master_username, password: var.master_password}`

**`infra/modules/aurora-vectordb/outputs.tf`**
- `cluster_endpoint` = `aws_rds_cluster.this.endpoint`
- `cluster_port` = `aws_rds_cluster.this.port`
- `secret_arn` = `aws_secretsmanager_secret.db.arn`
- `cluster_arn` = `aws_rds_cluster.this.arn`
- `db_name` = `var.db_name`

---

### Part C: Lambda VPC Module

**`infra/modules/lambda-vpc/variables.tf`**
- All 9 variables from `infra/modules/lambda/variables.tf` (function_name, handler, runtime, timeout, memory_size, source_dir, environment_variables, policy_statements, tags) — exact same types, defaults, descriptions
- Plus 3 new: `subnet_ids` (list(string), required), `security_group_ids` (list(string), required), `layers` (list(string), default `[]`)

**`infra/modules/lambda-vpc/main.tf`**
- Exact copy of `infra/modules/lambda/main.tf` with these changes to `aws_lambda_function.this`:
  - Add `vpc_config { subnet_ids = var.subnet_ids; security_group_ids = var.security_group_ids }` block
  - Add `layers = var.layers` attribute
- Add new resource: `aws_iam_role_policy_attachment.vpc` — role = `aws_iam_role.this.name`, policy_arn = `arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole`
- Everything else identical (archive_file, iam_role, iam_role_policy, basic_execution attachment, cloudwatch log group)

**`infra/modules/lambda-vpc/outputs.tf`**
- Identical to `infra/modules/lambda/outputs.tf` — 4 outputs using `.this` naming

---

### Part D: psycopg2 Layer Build Script

**`scripts/build-psycopg2-layer.sh`**
- Shebang `#!/bin/bash`, `set -euo pipefail`
- Define `SCRIPT_DIR` (dirname of script), `PROJECT_ROOT` (parent of SCRIPT_DIR), `OUTPUT_DIR` = `$PROJECT_ROOT/layers/psycopg2`
- `mkdir -p $OUTPUT_DIR`
- Check if Docker is available (`command -v docker`)
  - **Docker path:** Run `docker run --rm --platform linux/amd64 -v "$OUTPUT_DIR:/out" public.ecr.aws/lambda/python:3.11 pip install psycopg2-binary -t /out/python/lib/python3.11/site-packages/`
  - **Non-Docker path:** `mkdir -p $OUTPUT_DIR/python/lib/python3.11/site-packages/` then `pip install psycopg2-binary -t $OUTPUT_DIR/python/lib/python3.11/site-packages/ --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.11 --implementation cp`
- `cd $OUTPUT_DIR && zip -r psycopg2-layer.zip python/`
- Print success message with path to zip

---

### Part E: Migration Module

**`modules/migration-module/requirements.txt`**
- `alembic`
- `sqlalchemy`

**`modules/migration-module/src/__init__.py`** — empty file

**`modules/migration-module/src/handlers/__init__.py`** — empty file

**`modules/migration-module/src/handlers/run_migrations.py`**
- Handler function `handler(event, context)`
- Reads `SECRET_ARN` and `DB_NAME` from `os.environ`
- Creates boto3 Secrets Manager client
- Calls `get_secret_value(SecretId=secret_arn)`
- Parses JSON secret → extracts host, port, username, password, dbname
- Builds connection string: `postgresql://{username}:{password}@{host}:{port}/{dbname}`
- Creates SQLAlchemy `create_engine(url)`
- Opens connection
- Creates Alembic `Config` object pointing to `alembic.ini` path (resolved relative to this file: `os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "migrations", "alembic.ini")`)
- Sets `config.attributes["connection"] = connection`
- Calls `alembic.command.upgrade(config, "head")`
- Returns `{"statusCode": 200, "detail": {"message": "Migrations applied successfully"}}`
- Catches exceptions → returns `{"statusCode": 500, "detail": {"error": str(e)}}`

**`modules/migration-module/migrations/alembic.ini`**
- Standard Alembic ini
- `script_location = .` (since env.py is in same directory)
- `sqlalchemy.url =` (empty — set programmatically)

**`modules/migration-module/migrations/env.py`**
- Import alembic context, engine_from_config, pool
- `target_metadata = None` (we use raw SQL in migrations, not ORM models)
- Define `run_migrations_online()`:
  - Check `config.attributes.get("connection")` — **Lambda path**: use the provided connection directly
  - Else — **Local path**: get `DATABASE_URL` from `os.environ`, set it on config as `sqlalchemy.url`, create engine via `engine_from_config`, connect
  - In both paths: `context.configure(connection=connection, target_metadata=target_metadata)` then `context.run_migrations()`
- Call `run_migrations_online()`

**`modules/migration-module/migrations/script.py.mako`**
- Standard Alembic Mako template for new revision files

**`modules/migration-module/migrations/versions/001_initial_schema.py`**
- `revision = "001"`
- `down_revision = None`
- `upgrade()`:
  - `op.execute("CREATE EXTENSION IF NOT EXISTS vector")`
  - `op.create_table("video_chunks", ...)` with all 13 columns per spec schema
  - `op.execute(CREATE INDEX idx_video_chunks_embedding ... USING hnsw ... WITH (m=16, ef_construction=64))`
  - `op.create_index("idx_video_chunks_video_id", "video_chunks", ["video_id"])`
  - `op.create_index("idx_video_chunks_speaker", "video_chunks", ["speaker"])`
- `downgrade()`:
  - `op.drop_index("idx_video_chunks_speaker")`
  - `op.drop_index("idx_video_chunks_video_id")`
  - `op.drop_index("idx_video_chunks_embedding")`
  - `op.drop_table("video_chunks")`
  - `op.execute("DROP EXTENSION IF EXISTS vector")`

---

### Scripts

**`scripts/build-migration-module.sh`**
- Shebang, set -euo pipefail
- Define PROJECT_ROOT, TARGET_DIR = `$PROJECT_ROOT/modules/migration-module`
- Read requirements from `$TARGET_DIR/requirements.txt`
- Check Docker availability:
  - **Docker path:** `docker run --rm --platform linux/amd64 -v "$TARGET_DIR:/out" -w /out public.ecr.aws/lambda/python:3.11 pip install -r requirements.txt -t /out/`
  - **Non-Docker path:** `pip install -r $TARGET_DIR/requirements.txt -t $TARGET_DIR/ --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.11 --implementation cp`
- Print success

**`scripts/run-migrations.sh`**
- Shebang, set -euo pipefail
- `cd infra/environments/dev`
- Read TF outputs: `ENDPOINT=$(terraform output -raw aurora_cluster_endpoint)`, `SECRET_ARN=$(terraform output -raw aurora_secret_arn)`, `DB_NAME=$(terraform output -raw aurora_db_name)`
- Fetch secret from Secrets Manager via AWS CLI, extract username/password
- Build `DATABASE_URL=postgresql://{user}:{pass}@{host}:5432/{dbname}`
- Export DATABASE_URL
- `cd $PROJECT_ROOT/modules/migration-module/migrations`
- `alembic upgrade head`

---

### Part F: Dev Environment Wiring

**`infra/environments/dev/variables.tf`** — append:
- `aurora_master_password` (string, sensitive = true, description = "Aurora master password")

**`infra/environments/dev/main.tf`** — append (after existing resources, before EOF):

1. `module "networking"` block — source `../../modules/networking`, pass project_name, aws_region, tags = `local.common_tags`

2. `module "aurora_vectordb"` block — source `../../modules/aurora-vectordb`, pass project_name, subnet_ids from networking, security_group_id from networking (aurora SG), master_password from var, tags = `local.common_tags`

3. `aws_lambda_layer_version.psycopg2` resource — layer_name `${var.project_name}-psycopg2`, filename = `${path.module}/../../../layers/psycopg2/psycopg2-layer.zip`, compatible_runtimes = `["python3.11"]`, source_code_hash = `filebase64sha256(...)` of same path

4. `null_resource "build_migration_deps"` — triggers = `{ requirements_hash = filemd5("${path.module}/../../../modules/migration-module/requirements.txt") }`, provisioner local-exec runs `bash ${path.module}/../../../scripts/build-migration-module.sh`

5. `module "run_migrations"` — source `../../modules/lambda-vpc`, function_name `${var.project_name}-run-migrations`, handler `src.handlers.run_migrations.handler`, source_dir = migration-module path, timeout = 120, subnet_ids from networking, security_group_ids = `[module.networking.lambda_security_group_id]`, layers = `[aws_lambda_layer_version.psycopg2.arn]`, environment_variables = `{SECRET_ARN = module.aurora_vectordb.secret_arn, DB_NAME = module.aurora_vectordb.db_name}`, policy_statements = JSON with secretsmanager:GetSecretValue on aurora secret ARN, depends_on = `[null_resource.build_migration_deps]`

6. `null_resource "run_migrations"` — triggers = `{ handler_hash = filemd5 of handler file, migrations_hash = filemd5 of 001_initial_schema.py }`, depends_on = `[module.run_migrations, module.aurora_vectordb]`, provisioner local-exec runs `aws lambda invoke --function-name ${module.run_migrations.function_name} --payload '{}' --cli-binary-format raw-in-base64-out /tmp/migration-output.json && cat /tmp/migration-output.json`

**`infra/environments/dev/outputs.tf`** — append 5 outputs:
- `aurora_cluster_endpoint` = `module.aurora_vectordb.cluster_endpoint`
- `aurora_secret_arn` = `module.aurora_vectordb.secret_arn`
- `aurora_db_name` = `module.aurora_vectordb.db_name`
- `vpc_id` = `module.networking.vpc_id`
- `lambda_security_group_id` = `module.networking.lambda_security_group_id`

---

## Risks / Assumptions

1. **psycopg2-binary manylinux wheels** — the `--platform manylinux2014_x86_64 --only-binary=:all:` flag should grab the correct pre-built wheel. If pip version is old, this may fail; the Docker path is the safer fallback.
2. **Aurora engine version 17.7** — confirmed available in us-east-1. If AWS deprecates it, the cluster create will fail with a clear error.
3. **VPC endpoint cost** — 2 interface endpoints × 1 AZ × ~$0.01/hr = ~$14.40/month. Acceptable for workshop.
4. **null_resource ordering** — `depends_on` on both the Lambda module and Aurora ensures the invoke only happens after both exist. If Aurora is still starting up, the Lambda may fail to connect; the Lambda should handle transient connection errors gracefully (the retry is manual via re-apply).
5. **Migration module zip size** — alembic + sqlalchemy + src + migrations should be well under the 50MB Lambda zip limit.
6. **Single AZ for interface endpoints** — uses `tolist(...)[0]` which picks a deterministic but arbitrary subnet. Fine for workshop; production would use multiple AZs.

---

## Implementation Checklist

**Part A — Networking Module**

- [ ] 1. Create `infra/modules/networking/variables.tf` with `project_name`, `aws_region`, `tags` variables
- [ ] 2. Create `infra/modules/networking/main.tf` with default VPC data source, subnets data source, route tables data source, Lambda SG (no ingress, all egress), Aurora SG (TCP 5432 from Lambda SG, all egress), S3 gateway endpoint, Bedrock interface endpoint (single AZ, private DNS), Secrets Manager interface endpoint (single AZ, private DNS)
- [ ] 3. Create `infra/modules/networking/outputs.tf` with vpc_id, subnet_ids, lambda_security_group_id, aurora_security_group_id

**Part B — Aurora Vectordb Module**

- [ ] 4. Create `infra/modules/aurora-vectordb/variables.tf` with project_name, subnet_ids, security_group_id, db_name (default "ragdb"), master_username (default "ragadmin"), master_password (sensitive), tags
- [ ] 5. Create `infra/modules/aurora-vectordb/main.tf` with DB subnet group, Aurora cluster (aurora-postgresql 17.7, serverless v2 0.5–4 ACU, skip_final_snapshot, apply_immediately, enable_http_endpoint), cluster instance (db.serverless), Secrets Manager secret + version (JSON with host/port/dbname/username/password)
- [ ] 6. Create `infra/modules/aurora-vectordb/outputs.tf` with cluster_endpoint, cluster_port, secret_arn, cluster_arn, db_name

**Part C — Lambda VPC Module**

- [ ] 7. Create `infra/modules/lambda-vpc/variables.tf` — all 9 variables from lambda module plus subnet_ids, security_group_ids, layers
- [ ] 8. Create `infra/modules/lambda-vpc/main.tf` — copy of lambda/main.tf with vpc_config block, layers attribute, AWSLambdaVPCAccessExecutionRole policy attachment added
- [ ] 9. Create `infra/modules/lambda-vpc/outputs.tf` — identical to lambda/outputs.tf

**Part D — psycopg2 Layer Script**

- [ ] 10. Create `scripts/build-psycopg2-layer.sh` — Docker-optional build producing `layers/psycopg2/psycopg2-layer.zip` (linux/amd64 target)

**Part E — Migration Module**

- [ ] 11. Create `modules/migration-module/requirements.txt` with alembic and sqlalchemy
- [ ] 12. Create `modules/migration-module/src/__init__.py` (empty)
- [ ] 13. Create `modules/migration-module/src/handlers/__init__.py` (empty)
- [ ] 14. Create `modules/migration-module/src/handlers/run_migrations.py` — Lambda handler that reads secret, builds engine, runs alembic upgrade head
- [ ] 15. Create `modules/migration-module/migrations/alembic.ini` — standard config, script_location = `.`
- [ ] 16. Create `modules/migration-module/migrations/env.py` — dual-mode (Lambda connection or DATABASE_URL fallback)
- [ ] 17. Create `modules/migration-module/migrations/script.py.mako` — standard Alembic template
- [ ] 18. Create `modules/migration-module/migrations/versions/001_initial_schema.py` — pgvector extension, video_chunks table (all 13 columns), HNSW index, video_id index, speaker index (reversible upgrade/downgrade)

**Scripts**

- [ ] 19. Create `scripts/build-migration-module.sh` — Docker-optional pip install of alembic+sqlalchemy into migration-module dir (linux/amd64 target)
- [ ] 20. Create `scripts/run-migrations.sh` — local wrapper reading TF outputs, setting DATABASE_URL, running alembic upgrade head

**Part F — Dev Environment Wiring**

- [ ] 21. Add `aurora_master_password` variable (sensitive) to `infra/environments/dev/variables.tf`
- [ ] 22. Add `module "networking"` to `infra/environments/dev/main.tf`
- [ ] 23. Add `module "aurora_vectordb"` to `infra/environments/dev/main.tf`
- [ ] 24. Add `aws_lambda_layer_version.psycopg2` resource to `infra/environments/dev/main.tf`
- [ ] 25. Add `null_resource "build_migration_deps"` to `infra/environments/dev/main.tf`
- [ ] 26. Add `module "run_migrations"` (lambda-vpc) to `infra/environments/dev/main.tf`
- [ ] 27. Add `null_resource "run_migrations"` (invoke Lambda) to `infra/environments/dev/main.tf`
- [ ] 28. Add 5 new outputs to `infra/environments/dev/outputs.tf`

**Post-implementation (manual)**

- [ ] 29. Run `scripts/build-psycopg2-layer.sh` to produce the layer zip
- [ ] 30. Run `terraform init && terraform apply` in `infra/environments/dev/`
- [ ] 31. Verify via RDS Query Editor: pgvector extension, video_chunks table, indexes, alembic_version

---

**Review this plan. When ready, use /execute to implement it or /decompose to break it into smaller tasks.**
