# Embedding Module & SQS Wiring

**Deliverable:** SQS messages from the chunking stage trigger the embedding Lambda, which reads chunk JSON from S3, generates a 256-dimensional embedding via Amazon Bedrock Titan Text Embeddings V2, and upserts the chunk text and vector into the Aurora pgvector `video_chunks` table.

---

## Overview

1. Create the embedding Lambda module (Python): one SQS handler + service layer
2. Write unit tests for the embedding service
3. Deploy the embedding Lambda function using the `lambda-vpc` Terraform module (created in 001_infrastructure)
4. Wire the SQS embedding queue to the Lambda via an event source mapping
5. Verify end-to-end: upload audio → transcription → chunking → embedding → vectors in pgvector

---

## Prerequisites

- [ ] Stage 4 Part 1 (001_infrastructure) is complete and verified
- [ ] Aurora Serverless v2 is running with pgvector extension and `video_chunks` table (Alembic migration `001` applied)
- [ ] Secrets Manager secret contains valid database credentials
- [ ] VPC endpoints for S3, Bedrock Runtime, and Secrets Manager are available
- [ ] psycopg2 Lambda layer is deployed
- [ ] Bedrock `amazon.titan-embed-text-v2:0` is available (enabled by default)

---

## Architecture Context

```
SQS Embedding Queue (created in Stage 3)
    │
    ├── aws_lambda_event_source_mapping (batch_size = 1)
    │
    ▼
Embedding Lambda (VPC-attached via lambda-vpc module)
    │
    ├── 1. Parse SQS record body ──► {chunk_s3_key, bucket, video_id}
    │
    ├── 2. Read chunk JSON from S3
    │      via S3 Gateway VPC Endpoint (free)
    │      ──► chunk dict {chunk_id, video_id, text, start_time, end_time, ...}
    │
    ├── 3. Generate embedding via Bedrock Titan V2
    │      via Bedrock Runtime Interface VPC Endpoint
    │      ──► 256-dimensional float vector
    │
    └── 4. Upsert into Aurora pgvector
           via direct VPC access (port 5432)
           ──► INSERT INTO video_chunks ... ON CONFLICT (chunk_id) DO UPDATE
```

The embedding Lambda processes one SQS message per invocation (`batch_size = 1`). Each message contains a reference to one chunk JSON file in S3. The Lambda reads the chunk, generates an embedding, and inserts the record into pgvector. If the `chunk_id` already exists, the record is updated (idempotent upsert).

The Lambda runs inside the VPC to reach Aurora directly. It uses VPC endpoints to reach S3 (gateway) and Bedrock (interface) without a NAT Gateway.

---

## SQS Event Format (Lambda Input)

The embedding Lambda is triggered by SQS via an event source mapping. AWS delivers the SQS message batch as the Lambda event:

```json
{
  "Records": [
    {
      "messageId": "a1b2c3d4-5678-90ab-cdef-111111111111",
      "receiptHandle": "...",
      "body": "{\"chunk_s3_key\": \"chunks/hello-my_name_is_wes/chunk-001.json\", \"bucket\": \"production-rag-media-123456789012\", \"video_id\": \"hello-my_name_is_wes\", \"speaker\": \"Jane Doe\", \"title\": \"Building RAG Systems\"}",
      "attributes": { "..." },
      "messageAttributes": {},
      "md5OfBody": "...",
      "eventSource": "aws:sqs",
      "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:production-rag-embedding-queue",
      "awsRegion": "us-east-1"
    }
  ]
}
```

The `body` field is a JSON string published by the chunking Lambda's `publish_chunks` method. Parse it to extract:

| Field | Type | Description |
|-------|------|-------------|
| `chunk_s3_key` | `string` | S3 key of the chunk JSON file (e.g. `chunks/hello-my_name_is_wes/chunk-001.json`) |
| `bucket` | `string` | S3 bucket name |
| `video_id` | `string` | Video identifier |
| `speaker` | `string` (nullable) | Speaker name (from S3 object user metadata, propagated through pipeline) |
| `title` | `string` (nullable) | Video title (from S3 object user metadata, propagated through pipeline) |

---

## Chunk JSON Format (from S3)

The chunk JSON file read from S3 has this structure (created by the chunking stage):

```json
{
  "chunk_id": "hello-my_name_is_wes-chunk-001",
  "video_id": "hello-my_name_is_wes",
  "sequence": 1,
  "text": "Hello, my name is Wes. I'm going to talk about RAG pipelines...",
  "word_count": 487,
  "start_time": 0.0,
  "end_time": 45.2,
  "metadata": {
    "speaker": "Jane Doe",
    "title": "Building RAG Systems",
    "source_s3_key": "uploads/hello-my_name_is_wes.mp3",
    "total_chunks": 3
  }
}
```

The embedding service uses `text` for embedding generation and all fields for the pgvector upsert. The `speaker` and `title` are also available in the SQS message body (for cases where the embedding service needs them without reading the full chunk JSON).

---

## Bedrock Titan Text Embeddings V2

**Model ID:** `amazon.titan-embed-text-v2:0`

**Request:**

```json
{
  "inputText": "Hello, my name is Wes...",
  "dimensions": 256,
  "normalize": true
}
```

**Response:**

```json
{
  "embedding": [0.0123, -0.0456, 0.0789, ...],
  "inputTextTokenCount": 487
}
```

| Parameter | Value | Description |
|-----------|-------|-------------|
| `inputText` | chunk text | Text to embed (max 8,192 tokens) |
| `dimensions` | `256` | Output vector dimensions (256, 512, or 1024) |
| `normalize` | `true` | L2-normalize the output vector |

The `embedding` field is a list of 256 floats. The `inputTextTokenCount` is informational.

**Bedrock API call:**

```python
bedrock = boto3.client("bedrock-runtime")

response = bedrock.invoke_model(
    modelId="amazon.titan-embed-text-v2:0",
    contentType="application/json",
    accept="application/json",
    body=json.dumps({
        "inputText": chunk_text,
        "dimensions": 256,
        "normalize": True,
    }),
)

result = json.loads(response["body"].read())
embedding = result["embedding"]
```

---

## Upsert SQL

The embedding service inserts the chunk and its embedding into the `video_chunks` table. If the `chunk_id` already exists (e.g. from a re-run), the text and embedding are updated.

```sql
INSERT INTO video_chunks (
    chunk_id, video_id, sequence, text, embedding,
    speaker, title, start_time, end_time, source_s3_key, created_at
) VALUES (
    %s, %s, %s, %s, %s::vector,
    %s, %s, %s, %s, %s, NOW()
)
ON CONFLICT (chunk_id) DO UPDATE SET
    text = EXCLUDED.text,
    embedding = EXCLUDED.embedding,
    speaker = EXCLUDED.speaker,
    title = EXCLUDED.title,
    updated_at = NOW();
```

Parameters (positional):

1. `chunk_id` (string)
2. `video_id` (string)
3. `sequence` (int)
4. `text` (string)
5. `embedding` (string — the vector as a string like `[0.01, -0.02, ...]`)
6. `speaker` (string, nullable — from `chunk["metadata"]["speaker"]`)
7. `title` (string, nullable — from `chunk["metadata"]["title"]`)
8. `start_time` (float)
9. `end_time` (float)
10. `source_s3_key` (string — from `chunk["metadata"]["source_s3_key"]`)

---

## Resources

### Part A: Embedding Module (Python)

Application code for the embedding Lambda function. Follows the same thin-handlers-thick-services pattern as the transcribe and chunking modules.

**Directory structure:**

```
modules/embedding-module/
├── src/
│   ├── __init__.py
│   ├── handlers/
│   │   ├── __init__.py
│   │   └── process_embedding.py
│   ├── services/
│   │   ├── __init__.py
│   │   └── embedding_service.py
│   └── utils/
│       ├── __init__.py
│       └── logger.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   └── unit/
│       ├── __init__.py
│       └── test_embedding_service.py
├── requirements.txt
└── dev-requirements.txt
```

**Files to create:**

| File | Purpose |
|------|---------|
| `modules/embedding-module/src/handlers/process_embedding.py` | Lambda entry point: iterate SQS records, call service for each |
| `modules/embedding-module/src/services/embedding_service.py` | Business logic: read chunk, generate embedding, store in pgvector |
| `modules/embedding-module/src/utils/logger.py` | Shared logger utility — same as other modules |
| `modules/embedding-module/requirements.txt` | Runtime dependencies |
| `modules/embedding-module/dev-requirements.txt` | Test dependencies |
| All `__init__.py` files | Python package markers (empty files) |

---

#### process_embedding handler

**Input:** SQS event with `Records` array (see [SQS Event Format](#sqs-event-format-lambda-input))

**Output:** Not used (SQS event source mappings use success/failure for message deletion)

**Handler responsibilities:**

1. Iterate through `event["Records"]`
2. For each record, parse `json.loads(record["body"])` to get `chunk_s3_key`, `bucket`, `video_id`
3. Call `EmbeddingService.read_chunk(bucket, chunk_s3_key)` to get the chunk dict from S3
4. Call `EmbeddingService.generate_embedding(chunk["text"])` to get the 256-dim vector
5. Call `EmbeddingService.store_embedding(chunk, embedding)` to upsert into pgvector
6. Log success with `chunk_id` and `video_id`

**Error handling:** The embedding handler intentionally does **not** catch exceptions or return `statusCode` responses. Unlike the transcribe and chunking handlers (which are invoked by Step Functions and communicate results via return values), this handler is invoked by an SQS event source mapping. SQS event source mappings determine success or failure based on whether the Lambda invocation succeeds or throws — not on the return value. If any record fails, the unhandled exception causes the Lambda invocation to fail, and the SQS message returns to the queue after the visibility timeout expires. After 3 consecutive failures (`maxReceiveCount = 3`), the message moves to the DLQ.

**Environment variables used:**

| Variable | Description |
|----------|-------------|
| `SECRET_ARN` | Secrets Manager secret ARN for database credentials |
| `DB_NAME` | Database name (e.g. `ragdb`) |
| `EMBEDDING_DIMENSIONS` | Vector dimensions (e.g. `256`) |

---

#### EmbeddingService

Business logic layer. All S3 I/O, Bedrock calls, and database operations live here. Follows the same pattern as `TranscribeService` and `ChunkingService`: a class with boto3 clients created in `__init__`, instantiated once at module level for warm-invocation reuse.

| Method | Input | Output | Description |
|--------|-------|--------|-------------|
| `get_db_connection()` | — | `psycopg2.connection` | Read credentials from Secrets Manager, connect to Aurora via psycopg2. Cache connection for warm invocations. |
| `read_chunk(bucket, key)` | bucket name, S3 key | `dict` | Read and parse the chunk JSON from S3 |
| `generate_embedding(text)` | chunk text string | `list[float]` | Call Bedrock Titan V2 InvokeModel, return embedding vector |
| `store_embedding(chunk, embedding)` | chunk dict, embedding list | `None` | Upsert chunk + vector into `video_chunks` table |

**Constructor (`__init__`):**

- `self._s3 = boto3.client("s3")`
- `self._bedrock = boto3.client("bedrock-runtime")`
- `self._secretsmanager = boto3.client("secretsmanager")`
- `self._db_conn = None` (lazy connection, cached across warm invocations)
- `self._dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", "256"))`
- `self._secret_arn = os.environ["SECRET_ARN"]`
- `self._db_name = os.environ["DB_NAME"]`

**`get_db_connection` details:**

1. If `self._db_conn` is not `None` and connection is not closed, return it
2. Call `self._secretsmanager.get_secret_value(SecretId=self._secret_arn)`
3. Parse the JSON secret string to get `host`, `port`, `username`, `password`
4. Connect: `psycopg2.connect(host=host, port=port, dbname=self._db_name, user=username, password=password)`
5. Set `self._db_conn` and return it
6. On connection error, set `self._db_conn = None` and re-raise

**`generate_embedding` details:**

1. Call `self._bedrock.invoke_model(modelId="amazon.titan-embed-text-v2:0", contentType="application/json", accept="application/json", body=json.dumps({"inputText": text, "dimensions": self._dimensions, "normalize": True}))`
2. Parse response body JSON
3. Return `result["embedding"]`

**`store_embedding` details:**

1. Get connection via `self.get_db_connection()`
2. Create cursor
3. Convert embedding list to string format: `"[0.01, -0.02, ...]"`
4. Extract `speaker` and `title` from `chunk["metadata"]` (both nullable)
5. Execute the upsert SQL with parameters from the chunk dict (including `speaker`, `title`)
6. Commit the transaction
7. Close cursor (not connection — connection is cached)

---

#### Dependencies

**`requirements.txt`:**

```
boto3
psycopg2-binary
```

`psycopg2-binary` is listed for local development and testing. In the Lambda runtime, the psycopg2 Lambda layer provides the actual binary. The `requirements.txt` is not used for Lambda packaging (the module source directory is zipped directly by Terraform's `archive_file`).

**Lambda packaging note:** The `archive_file` data source in both `infra/modules/lambda/main.tf` and `infra/modules/lambda-vpc/main.tf` must exclude non-runtime files from the deployment zip. Add `excludes` to the `archive_file` data source in both modules:

```
data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = var.source_dir
  output_path = "/tmp/${var.function_name}.zip"
  excludes    = [
    ".venv",
    ".pytest_cache",
    "tests",
    "dev-requirements.txt",
  ]
}
```

Without these excludes, a `.venv` created inside a module directory for local development will push the deployment package past Lambda's 70 MB limit.

**`dev-requirements.txt`:**

```
pytest
moto[s3,secretsmanager]
```

---

### Part B: Unit Tests

**File:** `modules/embedding-module/tests/unit/test_embedding_service.py`

Test the embedding service logic. Mock external services (S3 via moto, Bedrock via unittest.mock, psycopg2 via unittest.mock).

| Test | Description |
|------|-------------|
| `test_read_chunk_parses_json` | Upload chunk JSON to moto S3, call `read_chunk`, verify returned dict matches |
| `test_read_chunk_missing_key_raises` | Call `read_chunk` with nonexistent key, verify `ClientError` raised |
| `test_generate_embedding_returns_vector` | Mock Bedrock `invoke_model` response, call `generate_embedding`, verify list of 256 floats |
| `test_generate_embedding_passes_correct_params` | Mock Bedrock, call `generate_embedding`, verify `modelId`, `dimensions`, and `normalize` in request |
| `test_store_embedding_executes_upsert` | Mock psycopg2 connection and cursor, call `store_embedding`, verify SQL `INSERT ... ON CONFLICT` executed with correct parameters |
| `test_store_embedding_commits` | Mock connection, call `store_embedding`, verify `connection.commit()` called |
| `test_handler_processes_single_record` | Mock service methods, invoke handler with one SQS record, verify `read_chunk`, `generate_embedding`, `store_embedding` each called once |
| `test_handler_processes_multiple_records` | Mock service methods, invoke handler with two SQS records, verify service methods called twice |

**`conftest.py` fixtures:**

| Fixture | Description |
|---------|-------------|
| `sample_chunk` | A dict matching the chunk JSON schema with text, video_id, chunk_id, etc. |
| `sample_sqs_event` | A dict matching the SQS event format with one Record whose body contains chunk_s3_key, bucket, video_id |
| `s3_bucket` | Moto-mocked S3 bucket with a sample chunk JSON uploaded |

---

### Part C: Embedding Lambda Deployment (Terraform)

Add one Lambda module call to `infra/environments/dev/main.tf` using the `infra/modules/lambda-vpc` module (created in 001_infrastructure).

| Setting | Value |
|---------|-------|
| Function name | `${var.project_name}-embed-chunk` |
| Handler | `src.handlers.process_embedding.handler` |
| Source dir | `${path.module}/../../../modules/embedding-module` |
| Runtime | `python3.11` (module default) |
| Timeout | `120` |
| Memory | `256` (module default) |
| Layers | `[aws_lambda_layer_version.psycopg2.arn]` |
| Subnet IDs | `module.networking.subnet_ids` |
| Security group IDs | `[module.networking.lambda_security_group_id]` |

**Environment variables:**

| Variable | Value |
|----------|-------|
| `SECRET_ARN` | `module.aurora_vectordb.secret_arn` |
| `DB_NAME` | `module.aurora_vectordb.db_name` |
| `EMBEDDING_DIMENSIONS` | `"256"` |

**IAM permissions:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "${module.media_bucket.bucket_arn}/chunks/*"
    },
    {
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel"],
      "Resource": "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0"
    },
    {
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "${module.aurora_vectordb.secret_arn}"
    },
    {
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes"
      ],
      "Resource": "${aws_sqs_queue.embedding.arn}"
    }
  ]
}
```

**SQS event source mapping:**

| Resource | Type | Key Settings |
|----------|------|-------------|
| `aws_lambda_event_source_mapping.embedding` | Event source mapping | `event_source_arn` = `aws_sqs_queue.embedding.arn`, `function_name` = embedding Lambda ARN, `batch_size` = `1`, `enabled` = `true` |

---

### Part D: Outputs

**Add to `infra/environments/dev/outputs.tf`:**

| Output | Value | Description |
|--------|-------|-------------|
| `embedding_function_name` | `module.embed_chunk.function_name` | Embedding Lambda function name |

---

## Implementation Checklist

- [ ] 1. Create `modules/embedding-module/requirements.txt` with `boto3`, `psycopg2-binary`
- [ ] 2. Create `modules/embedding-module/dev-requirements.txt` with `pytest`, `moto[s3,secretsmanager]`
- [ ] 3. Create all `__init__.py` files (`src/`, `src/handlers/`, `src/services/`, `src/utils/`, `tests/`, `tests/unit/`)
- [ ] 4. Create `modules/embedding-module/src/utils/logger.py`
- [ ] 5. Create `modules/embedding-module/src/services/embedding_service.py` with `read_chunk`, `generate_embedding`, `store_embedding`, `get_db_connection`
- [ ] 6. Create `modules/embedding-module/src/handlers/process_embedding.py` handler
- [ ] 7. Create `modules/embedding-module/tests/conftest.py` with shared fixtures
- [ ] 8. Create `modules/embedding-module/tests/unit/test_embedding_service.py` with unit tests
- [ ] 9. Add `module "embed_chunk"` (lambda-vpc module) to `infra/environments/dev/main.tf` with VPC config, psycopg2 layer, environment variables, and IAM permissions
- [ ] 10. Add `aws_lambda_event_source_mapping.embedding` to `infra/environments/dev/main.tf`
- [ ] 11. Add `embedding_function_name` output to `infra/environments/dev/outputs.tf`
- [ ] 12. Run `terraform init && terraform apply` in `infra/environments/dev/`
- [ ] 13. Verify: upload sample audio and confirm the full pipeline completes (transcription → chunking → embedding)
- [ ] 14. Verify: query pgvector to confirm embeddings are stored

---

## Verification

### Step 1: Deploy

```bash
cd infra/environments/dev
terraform init
terraform plan -var="aurora_master_password=YourSecurePassword123!"
terraform apply -var="aurora_master_password=YourSecurePassword123!"
```

### Step 2: Check SQS queue has messages (from previous chunking runs)

If messages already exist in the queue from Stage 3 testing, the embedding Lambda should start processing them immediately after deployment. Check:

```bash
QUEUE_URL=$(terraform output -raw embedding_queue_url)
aws sqs get-queue-attributes \
  --queue-url "$QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages \
  --query "Attributes.ApproximateNumberOfMessages" \
  --output text
```

If the queue is empty, upload a new sample audio file to trigger the full pipeline:

```bash
BUCKET=$(terraform output -raw media_bucket_name)
aws s3 cp ../../../samples/hello-my_name_is_wes.mp3 \
  "s3://${BUCKET}/uploads/test-embed-$(date +%s).mp3" \
  --metadata '{"speaker":"Wesley Reisz","title":"Hello, my name is Wes"}'
```

### Step 3: Monitor the embedding Lambda

```bash
aws logs tail /aws/lambda/production-rag-embed-chunk --follow --since 5m
```

Expected: Log entries showing chunk processing — reading from S3, generating embeddings, inserting into pgvector.

### Step 4: Wait for pipeline completion

If a new upload was triggered, wait for the Step Functions execution to complete (transcription + chunking), then wait an additional 30-60 seconds for SQS delivery and embedding processing.

```bash
STATE_MACHINE_ARN=$(terraform output -raw state_machine_arn)

EXECUTION_ARN=$(aws stepfunctions list-executions \
  --state-machine-arn "$STATE_MACHINE_ARN" \
  --max-results 1 \
  --query 'executions[0].executionArn' \
  --output text)

aws stepfunctions describe-execution \
  --execution-arn "$EXECUTION_ARN" \
  --query '{status: status}' --output table
```

Expected: `SUCCEEDED`

### Step 5: Verify SQS queue is drained

```bash
aws sqs get-queue-attributes \
  --queue-url "$QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
  --output table
```

Expected: Both counts are `0` (all messages processed).

### Step 6: Verify DLQ is empty

```bash
DLQ_URL=$(aws sqs get-queue-url --queue-name production-rag-embedding-dlq --query 'QueueUrl' --output text)
aws sqs get-queue-attributes \
  --queue-url "$DLQ_URL" \
  --attribute-names ApproximateNumberOfMessages \
  --query "Attributes.ApproximateNumberOfMessages" \
  --output text
```

Expected: `0` (no failed messages).

### Step 7: Query pgvector to verify embeddings

```bash
ENDPOINT=$(terraform output -raw aurora_cluster_endpoint)
DB_NAME=$(terraform output -raw aurora_db_name)

PGPASSWORD=YourSecurePassword123! psql -h "$ENDPOINT" -U ragadmin -d "$DB_NAME" -c \
  "SELECT chunk_id, video_id, sequence, left(text, 60) AS text_preview,
          array_length(string_to_array(embedding::text, ','), 1) AS dims,
          start_time, end_time
   FROM video_chunks
   ORDER BY video_id, sequence;"
```

Expected: One row per chunk with 256 dimensions, matching the chunks stored in S3.

### Step 8: Verify embedding dimensions

```bash
PGPASSWORD=YourSecurePassword123! psql -h "$ENDPOINT" -U ragadmin -d "$DB_NAME" -c \
  "SELECT chunk_id,
          array_length(string_to_array(embedding::text, ','), 1) AS dims
   FROM video_chunks
   LIMIT 3;"
```

Expected: `dims` = `256` for all rows.

### Step 9: Test similarity search

```bash
PGPASSWORD=YourSecurePassword123! psql -h "$ENDPOINT" -U ragadmin -d "$DB_NAME" -c \
  "SELECT chunk_id, left(text, 80) AS text_preview,
          1 - (embedding <=> (SELECT embedding FROM video_chunks LIMIT 1)) AS similarity
   FROM video_chunks
   ORDER BY embedding <=> (SELECT embedding FROM video_chunks LIMIT 1)
   LIMIT 5;"
```

Expected: The first row has `similarity = 1.0` (identical vector), other rows have similarity < 1.0.

---

## Success Criteria

| Criterion | How to verify |
|-----------|---------------|
| Embedding module code exists | `modules/embedding-module/src/` has handlers and services directories with Python files |
| Embedding Lambda deployed | `aws lambda list-functions` shows `production-rag-embed-chunk` |
| Lambda is VPC-attached | `aws lambda get-function-configuration --function-name production-rag-embed-chunk` shows `VpcConfig` with subnet and security group IDs |
| Lambda has psycopg2 layer | Function configuration shows the psycopg2 layer ARN in `Layers` |
| SQS event source mapping exists | `aws lambda list-event-source-mappings --function-name production-rag-embed-chunk` shows the embedding queue mapping |
| Event source mapping batch size is 1 | Mapping `BatchSize` is `1` |
| Embedding Lambda processes messages | CloudWatch logs show successful chunk processing |
| SQS queue drains after processing | `ApproximateNumberOfMessages` goes to `0` after Lambda processes |
| DLQ is empty | No messages in `production-rag-embedding-dlq` |
| Vectors stored in pgvector | `SELECT count(*) FROM video_chunks` returns > 0 |
| Embedding dimensions are 256 | All stored vectors have 256 dimensions |
| Upsert is idempotent | Re-processing the same chunk updates rather than duplicates the row |
| Chunk data is complete | Each `video_chunks` row has non-null `chunk_id`, `video_id`, `text`, `embedding`, `start_time`, `end_time` |
| Speaker/title stored | `speaker` and `title` columns are populated when S3 object metadata was set at upload time |
| Similarity search works | `ORDER BY embedding <=> query_vector` returns results ordered by relevance |
| Unit tests pass | `cd modules/embedding-module && python -m pytest tests/` passes |
