# Product Requirements Document (PRD)
# Workshop: Building a Production-Grade RAG Pipeline

**Author:** Wesley Reisz
**Conference:** Arc of AI (Senior Developer Conference)
**Version:** 1.0
**Date:** 2026-02-26
**Status:** Draft

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Workshop Overview](#2-workshop-overview)
3. [Target Audience & Prerequisites](#3-target-audience--prerequisites)
4. [Reference Architecture](#4-reference-architecture)
5. [Technology Stack & Service Decisions](#5-technology-stack--service-decisions)
6. [System Architecture](#6-system-architecture)
7. [Module Specifications](#7-module-specifications)
8. [Infrastructure Design](#8-infrastructure-design)
9. [Workshop Stages & RIPER-5 Mapping](#9-workshop-stages--riper-5-mapping)
10. [Cost Analysis](#10-cost-analysis)
11. [Deliverables & Success Criteria](#11-deliverables--success-criteria)
12. [Risk Assessment & Mitigations](#12-risk-assessment--mitigations)
13. [Appendices](#13-appendices)

---

## 1. Executive Summary

This workshop teaches senior developers how to build, orchestrate, and operate a production-grade Retrieval-Augmented Generation (RAG) pipeline on AWS. Participants will construct an end-to-end system that ingests video content, transcribes audio, chunks text, generates embeddings, stores vectors, and exposes a semantic search API. The final integration connects the retrieval service to Cursor IDE via the Model Context Protocol (MCP), demonstrating how RAG pipelines feed into agentic developer workflows.

The system is adapted from a real-world production pipeline ([wesreisz/video-pipeline](https://github.com/wesreisz/video-pipeline)) with two key modifications to reduce third-party costs and keep the stack fully AWS-native:

| Original Stack | Workshop Stack | Rationale |
|---|---|---|
| OpenAI Embeddings API | Amazon Bedrock Titan Text Embeddings V2 | AWS-native, $0.02/M tokens, no API key management |
| Pinecone Vector DB | Amazon Aurora Serverless v2 + pgvector | ~$0.12/hr, familiar PostgreSQL, auto-pause capable |

The workshop follows a **spec-driven development approach** using the **RIPER-5 protocol** (Research, Innovate, Plan, Execute, Review) for each stage, ensuring participants understand not just *what* to build but *why* each decision was made and *how* to reason about production systems.

---

## 2. Workshop Overview

### 2.1 Workshop Identity

- **Title:** Building a Production-Grade RAG Pipeline
- **Subtitle:** From Video Ingestion to IDE-Integrated Semantic Search
- **Duration:** 8 hours (including breaks)
- **Format:** Instructor-led, hands-on, spec-driven
- **Max Participants:** 30 (recommended for hands-on support)

### 2.2 Learning Outcomes

By the end of this workshop, participants will be able to:

1. Design and implement a multi-stage data ingestion pipeline using AWS serverless services
2. Orchestrate asynchronous processing workflows with AWS Step Functions
3. Generate vector embeddings using Amazon Bedrock and store them in a PostgreSQL-based vector database
4. Build a semantic search API that retrieves contextually relevant content
5. Expose retrieval capabilities through an MCP server for IDE integration
6. Reason about production concerns: observability, retries, error handling, cost, and security

### 2.3 What Makes This Workshop Different

- **Orchestration-first design:** Participants refactor loose event-driven triggers into an explicitly orchestrated Step Functions workflow, gaining visibility, retry semantics, and state management.
- **Spec-driven development:** Each module is built from a specification, not copy-pasted code. Participants practice the RIPER-5 methodology used in AI-assisted development.
- **Developer experience as a first-class concern:** The pipeline culminates in an MCP server, making video knowledge queryable directly from Cursor IDE. This is foundational to building context-aware agentic systems.
- **Cost-conscious AWS-native stack:** Every service choice is justified against cost, simplicity, and scalability trade-offs.

### 2.4 Workshop Schedule

| Time | Stage | Duration | Topic |
|------|-------|----------|-------|
| 09:00 | 1 | 45 min | Introduction & Architecture Overview |
| 09:45 | 2 | 45 min | Video Upload & Workflow Trigger |
| 10:30 | — | 15 min | Break |
| 10:45 | 3 | 90 min | Transcription with AWS Transcribe |
| 12:15 | — | 60 min | Lunch |
| 13:15 | 4 | 75 min | Chunking & Queue-Based Fan-Out |
| 14:30 | 5 | 75 min | Embedding & Vector Storage |
| 15:45 | — | 15 min | Break |
| 16:00 | 6 | 75 min | Building the Retrieval / Question Service |
| 17:15 | 7 | 60 min | MCP Server & Cursor Integration |
| 18:15 | 8 | 30 min | Wrap-Up: Production Concerns & Next Steps |
| 18:45 | — | — | End |

---

## 3. Target Audience & Prerequisites

### 3.1 Target Audience

Senior software developers and architects who:

- Have production experience building backend systems
- Are familiar with cloud services (AWS preferred, but Azure/GCP experience transfers)
- Want to understand RAG pipelines beyond toy demos
- Are interested in AI-assisted development workflows and agentic architectures

### 3.2 Technical Prerequisites

**Required:**

- Python 3.11+ proficiency
- AWS account with admin access (or provided workshop account)
- AWS CLI v2 installed and configured
- Terraform >= 1.5 installed
- Cursor IDE installed (free tier is sufficient)
- Git and basic command-line fluency
- Familiarity with REST APIs and JSON

**Helpful but not required:**

- Experience with AWS Lambda, S3, Step Functions
- Familiarity with PostgreSQL
- Understanding of vector embeddings and similarity search
- Prior exposure to LLMs or RAG concepts

### 3.3 Pre-Workshop Setup

Participants must complete before arrival:

1. **AWS Account:** Active account with billing enabled; ideally a sandbox/dev account
2. **AWS CLI:** Configured with credentials (`aws sts get-caller-identity` succeeds)
3. **Terraform:** Installed and on PATH (`terraform --version` succeeds)
4. **Python 3.11+:** Installed with `pip` and `venv` support
5. **Cursor IDE:** Installed with MCP support enabled
6. **Clone workshop repo:** `git clone <workshop-repo-url>`
7. **Enable Bedrock model access:** In the AWS Console, navigate to Amazon Bedrock > Model Access and request access to `amazon.titan-embed-text-v2:0` and `anthropic.claude-3-haiku` (or equivalent)

### 3.4 Provided to Participants

- Workshop repository with scaffold code, specs, and Terraform modules
- Sample video files (short conference talks, 5-10 minutes each)
- Pre-built Terraform bootstrap for remote state
- Cursor rules (`.cursor/rules/`) for AI-assisted development
- Architecture diagrams and reference documentation

---

## 4. Reference Architecture

### 4.1 High-Level Data Flow

```
┌─────────────┐     ┌──────────────┐     ┌───────────────┐     ┌─────────────┐     ┌──────────────┐
│   Video      │     │  AWS          │     │  Chunking      │     │  Embedding   │     │  Aurora       │
│   Upload     │────▶│  Transcribe   │────▶│  Service       │────▶│  Service     │────▶│  pgvector     │
│   (S3)       │     │  (Lambda)     │     │  (Lambda)      │     │  (Lambda)    │     │  (Vector DB)  │
└─────────────┘     └──────────────┘     └───────────────┘     └─────────────┘     └──────────────┘
       │                                                                                    │
       │              ┌──────────────────────────────────────────────────────┐               │
       └─────────────▶│           AWS Step Functions (Orchestrator)          │◀──────────────┘
                      └──────────────────────────────────────────────────────┘
                                                                                    │
                                              ┌─────────────────┐                   │
                                              │  Question        │                   │
                                              │  Service         │◀──────────────────┘
                                              │  (API Gateway)   │
                                              └────────┬────────┘
                                                       │
                                              ┌────────▼────────┐
                                              │  MCP Server      │
                                              │  (Cursor IDE)    │
                                              └─────────────────┘
```

### 4.2 Event Flow (Detailed)

```
S3 Upload ──▶ EventBridge Rule ──▶ Step Functions State Machine
                                                          │
                                                          ├── State 1: Validate Input
                                                          ├── State 2: Start Transcription Job
                                                          ├── State 3: Wait for Transcription
                                                          ├── State 4: Chunk Transcript
                                                          ├── State 5: Generate Embeddings (fan-out via SQS)
                                                          └── State 6: Confirm Indexing Complete
```

### 4.3 Differences from Reference Codebase

| Aspect | Reference (video-pipeline) | Workshop (production-rag) |
|--------|---------------------------|--------------------------|
| Embeddings | OpenAI `text-embedding-ada-002` | Amazon Bedrock Titan Text Embeddings V2 |
| Vector DB | Pinecone (managed SaaS) | Aurora Serverless v2 + pgvector |
| Vector dimensions | 1536 (OpenAI) | 1024 (Titan V2, configurable to 256/512) |
| API key management | Secrets Manager (OpenAI + Pinecone keys) | IAM roles only (no external API keys for core pipeline) |
| Cost model | Per-token (OpenAI) + per-vector (Pinecone) | Per-token (Bedrock) + per-ACU-hour (Aurora) |
| MCP Server | Not included | Included as final stage |
| Step Functions | Exists in reference | Retained and adapted |

---

## 5. Technology Stack & Service Decisions

### 5.1 AWS Services Used

| Service | Purpose | Pricing Model | Workshop Est. Cost |
|---------|---------|---------------|-------------------|
| **Amazon S3** | Video/media storage, transcription output, chunk storage | $0.023/GB/mo | < $0.10 |
| **Amazon EventBridge** | Event routing from S3 to Step Functions (via S3 native notifications) | $1.00/M events | < $0.01 |
| **AWS Step Functions** | Pipeline orchestration | $0.025/1K transitions | < $0.01 |
| **AWS Lambda** | Compute for all modules | $0.20/M requests + duration | < $0.50 |
| **Amazon Transcribe** | Video/audio to text | $0.024/min (standard) | ~$2.40 (100 min) |
| **Amazon SQS** | Message queuing for chunk fan-out | $0.40/M requests | < $0.01 |
| **Amazon Bedrock** | Titan Text Embeddings V2 | $0.02/M tokens | < $0.10 |
| **Aurora Serverless v2** | pgvector-based vector storage | $0.12/ACU-hr (min 0.5 ACU) | ~$1.00 (8 hrs) |
| **API Gateway** | REST API for question service | $3.50/M requests | < $0.01 |
| **Secrets Manager** | Store any remaining secrets | $0.40/secret/mo | < $0.40 |
| **IAM** | Service roles and policies | Free | $0.00 |

**Estimated total workshop cost per participant: ~$5-10 for a full day (assuming cleanup after)**

### 5.2 Decision: Amazon Bedrock Titan Embeddings V2

**Why Titan V2 over OpenAI:**

1. **Cost:** $0.02/M tokens vs $0.13/M tokens (OpenAI ada-002). 85% cheaper.
2. **No API key:** Uses IAM authentication. No Secrets Manager entries needed for the embedding pipeline.
3. **Flexible dimensions:** Output 256, 512, or 1024 dimensions. Smaller dimensions = faster search, less storage.
4. **AWS-native:** No external network calls. Lower latency from Lambda.
5. **Workshop simplicity:** Participants only need an AWS account, not an OpenAI account.

**Trade-offs:**

- Model quality is comparable but not identical to OpenAI embeddings
- Requires Bedrock model access to be enabled (one-time console step)
- Less community documentation than OpenAI embeddings

### 5.3 Decision: Aurora Serverless v2 + pgvector

**Why Aurora+pgvector over Pinecone:**

1. **Cost:** ~$0.12/hr vs Pinecone's pod-based pricing (~$0.096/hr for p1.x1, but with commitments). Aurora Serverless v2 scales down to 0.5 ACU ($0.06/hr) when idle.
2. **No external account:** No Pinecone signup or API key needed.
3. **Familiar technology:** PostgreSQL is known to most senior developers. SQL-based vector queries are debuggable.
4. **Full control:** Can inspect data directly, run ad-hoc queries, join with metadata tables.
5. **Production-proven:** pgvector supports IVFFlat and HNSW indexes for scalable approximate nearest neighbor search.

**Why Aurora Serverless v2 specifically (over OpenSearch Serverless):**

- OpenSearch Serverless vector search has a minimum of ~4 OCUs ($0.96/hr) even when idle
- Aurora Serverless v2 scales down to 0.5 ACU ($0.06/hr) — much cheaper when idle
- For a cost-conscious workshop, Aurora is ~10x cheaper when idle
- PostgreSQL + pgvector is conceptually simpler than OpenSearch's JSON-based API

**Trade-offs:**

- pgvector is not a purpose-built vector database; at very large scale (100M+ vectors), dedicated solutions perform better
- Requires VPC configuration for Aurora (adds Terraform complexity)
- SQL syntax for vector search is less intuitive than Pinecone's Python SDK
- No built-in hybrid search (text + vector) without additional configuration

### 5.4 Decision: Retain Step Functions Orchestration

The reference codebase uses Step Functions for pipeline orchestration. This is retained because:

1. **Visibility:** The Step Functions console provides a visual execution graph — invaluable for debugging and teaching
2. **Retries:** Built-in retry with exponential backoff at each state
3. **State management:** Pass data between stages without external state stores
4. **Error handling:** Catch blocks and fallback states for graceful failure handling
5. **Workshop narrative:** Refactoring from loose event triggers to explicit orchestration is a key learning moment

### 5.5 Python Version & Dependencies

- **Python:** 3.11 (Lambda runtime support, performance improvements)
- **Key libraries per module:**

| Module | Key Dependencies |
|--------|-----------------|
| Transcribe | `boto3`, `botocore` |
| Chunking | `boto3`, `tiktoken` (or custom tokenizer) |
| Embedding | `boto3` (Bedrock runtime), `psycopg2-binary`, `pgvector` |
| Question | `boto3` (Bedrock runtime), `psycopg2-binary`, `pgvector` |
| MCP Server | `mcp`, `httpx`, `pydantic` |
| Migrations | `alembic`, `sqlalchemy`, `psycopg2-binary`, `pgvector` |

---

## 6. System Architecture

### 6.1 Project Structure

```
production-rag/
├── .cursor/
│   └── rules/                          # Cursor rules for AI-assisted dev
│       ├── project-architecture.mdc
│       ├── project-structure.mdc
│       ├── python.mdc
│       ├── pytest.mdc
│       └── terraform.mdc
├── infra/
│   ├── bootstrap/                      # One-time Terraform state setup
│   ├── environments/
│   │   └── dev/                        # Dev environment Terraform
│   │       ├── main.tf
│   │       ├── variables.tf
│   │       ├── outputs.tf
│   │       ├── providers.tf
│   │       └── deploy.sh
│   └── modules/                        # Reusable Terraform modules
│       ├── s3/                         # S3 buckets (media, transcripts)
│       ├── lambda/                     # Generic Lambda (transcribe, chunking)
│       ├── lambda-vpc/                 # VPC-attached Lambda (embedding, question)
│       ├── aurora-vectordb/            # Aurora Serverless v2 + pgvector
│       ├── step-functions/             # Pipeline orchestration
│       ├── sqs/                        # SQS queues
│       ├── api-gateway/                # REST API for question service
│       ├── networking/                 # VPC endpoints, security groups
│       └── secrets/                    # Secrets Manager
├── modules/
│   ├── transcribe-module/
│   │   ├── specs/features/             # BDD-style feature specs
│   │   ├── src/
│   │   │   ├── handlers/               # Lambda entry point
│   │   │   ├── services/               # Business logic
│   │   │   ├── models/                 # Data structures
│   │   │   └── utils/                  # Helpers (logger, etc.)
│   │   ├── tests/
│   │   │   ├── unit/
│   │   │   └── conftest.py
│   │   ├── requirements.txt
│   │   └── dev-requirements.txt
│   ├── chunking-module/
│   │   ├── specs/features/
│   │   ├── src/
│   │   │   ├── handlers/
│   │   │   ├── services/
│   │   │   ├── models/
│   │   │   └── utils/
│   │   ├── tests/
│   │   ├── requirements.txt
│   │   └── dev-requirements.txt
│   ├── embedding-module/
│   │   ├── specs/features/
│   │   ├── src/
│   │   │   ├── handlers/
│   │   │   ├── services/               # Bedrock embedding service
│   │   │   ├── models/
│   │   │   └── utils/
│   │   ├── tests/
│   │   ├── requirements.txt
│   │   └── dev-requirements.txt
│   ├── question-module/
│   │   ├── specs/features/
│   │   ├── openapi/                    # OpenAPI spec for REST API
│   │   ├── src/
│   │   │   ├── handlers/
│   │   │   ├── services/               # Bedrock + pgvector query service
│   │   │   ├── models/
│   │   │   └── utils/
│   │   ├── tests/
│   │   ├── requirements.txt
│   │   └── dev-requirements.txt
│   └── mcp-server/
│       ├── specs/
│       ├── src/
│       │   ├── server.py               # MCP server entry point
│       │   ├── tools/                   # MCP tool definitions
│       │   └── config.py
│       ├── tests/
│       ├── requirements.txt
│       └── dev-requirements.txt
├── migrations/                        # Alembic database migrations (version-tracked schema changes)
├── samples/
│   └── sample.mp3                      # Sample audio for testing
├── specs/
│   └── prompts/                        # Spec-driven development prompts
│       ├── 0-project-setup.md
│       ├── 1-s3-upload-trigger.md
│       ├── 2-transcription.md
│       ├── 3-chunking.md
│       ├── 4-embedding.md
│       ├── 5-question-service.md
│       ├── 6-mcp-server.md
│       └── 7-step-functions.md
├── PRD.md                              # This document
├── requirements.txt                    # Root-level shared dependencies
├── dev-requirements.txt                # Dev/test dependencies
└── README.md
```

### 6.2 Core Architecture Principles

1. **Event-Driven with Explicit Orchestration:** S3 events trigger the pipeline; Step Functions orchestrate the stages. Individual stages communicate through events and shared S3 storage, but the workflow is explicitly defined and observable.

2. **Serverless-First:** All compute runs on AWS Lambda. No servers to manage. Pay only for what you use. This is critical for a workshop where resources should cost near-zero when idle.

3. **Module Independence:** Each module (transcribe, chunking, embedding, question) is independently deployable with its own dependencies, tests, and specs. No cross-module imports.

4. **Thin Handlers, Thick Services:** Lambda handlers are thin entry points that validate input and delegate to a service layer. All business logic lives in `services/`. This makes code testable without Lambda runtime.

5. **Spec-Driven Development:** Every module has a `specs/features/` directory containing behavioral specifications. These specs drive the implementation and serve as documentation.

6. **Infrastructure as Code:** All AWS resources are defined in Terraform. No click-ops. Reproducible across environments.

### 6.3 EventBridge Event Format

S3 sends events directly to EventBridge via native S3 notifications (enabled per-bucket). The S3 trigger event uses this format:

```json
{
  "source": "aws.s3",
  "detail-type": "Object Created",
  "detail": {
    "bucket": {
      "name": "production-rag-media-<account-id>"
    },
    "object": {
      "key": "uploads/video-123.mp4",
      "size": 15728640
    },
    "reason": "PutObject"
  }
}
```

Inter-service events within Step Functions follow this canonical format:

```json
{
  "source": "video-pipeline.<module-name>",
  "detail-type": "<ModuleName>.<Action>Completed",
  "detail": {
    "bucket": {
      "name": "production-rag-media-<account-id>"
    },
    "object": {
      "key": "uploads/video-123.mp4"
    },
    "records": [
      {
        "chunk_id": "video-123-chunk-001",
        "text": "...",
        "s3_key": "chunks/video-123/chunk-001.json"
      }
    ],
    "metadata": {
      "video_id": "video-123",
      "speaker": "Jane Doe",
      "title": "Building RAG Systems",
      "duration_seconds": 600,
      "timestamp": "2026-02-26T09:00:00Z"
    },
    "status": "COMPLETED"
  }
}
```

### 6.4 Lambda Response Format

All Lambda functions return this structure for Step Functions compatibility:

```json
{
  "statusCode": 200,
  "detail": {
    "records": [...],
    "metadata": {...},
    "processing": {
      "module": "transcribe",
      "duration_ms": 45000,
      "items_processed": 1
    }
  },
  "body": "{\"message\": \"Transcription completed\", \"transcript_key\": \"transcripts/video-123.json\"}"
}
```

---

## 7. Module Specifications

### 7.1 Transcribe Module

**Purpose:** Accept an S3 video/audio file reference, start an AWS Transcribe job, wait for completion, and store the raw transcript in S3.

**Input (from Step Functions):**
```json
{
  "detail": {
    "bucket": {
      "name": "production-rag-media-xxx"
    },
    "object": {
      "key": "uploads/sample.mp4"
    },
    "metadata": {
      "video_id": "video-123",
      "speaker": "Jane Doe",
      "title": "Building RAG Systems"
    }
  }
}
```

**Processing Steps:**

1. Extract S3 bucket and key from the incoming event
2. Generate a unique transcription job name from the video ID
3. Call `transcribe:StartTranscriptionJob` with:
   - Media format detection from file extension
   - Output bucket set to a designated transcripts prefix
   - Language code: `en-US` (configurable)
4. Return the job name and output location to Step Functions
5. Step Functions uses a Wait + Poll loop (or callback) to check job status
6. On completion, the raw transcript JSON is already in S3

**Output (to Step Functions):**
```json
{
  "statusCode": 200,
  "detail": {
    "transcription_job_name": "video-123-transcribe",
    "transcript_s3_key": "transcripts/video-123/raw.json",
    "metadata": { "...propagated..." }
  }
}
```

**Error Handling:**

- Transcribe job failures → caught by Step Functions, retried up to 3 times with exponential backoff
- S3 access errors → fail fast with descriptive error
- Timeout → Step Functions timeout state after 30 minutes

**Dependencies:** `boto3`

**Terraform Resources:** Lambda function, IAM role with `transcribe:*` and `s3:GetObject/PutObject` permissions

---

### 7.2 Chunking Module

**Purpose:** Take a raw transcript from S3, split it into retrieval-friendly chunks with metadata, and publish them to SQS for fan-out processing.

**Input (from Step Functions):**
```json
{
  "detail": {
    "transcript_s3_key": "transcripts/video-123/raw.json",
    "metadata": {
      "video_id": "video-123",
      "speaker": "Jane Doe",
      "title": "Building RAG Systems"
    }
  }
}
```

**Processing Steps:**

1. Read raw transcript JSON from S3
2. Extract transcript text segments with timestamps
3. Chunk the text using a sliding window strategy:
   - **Chunk size:** ~500 tokens (configurable)
   - **Overlap:** ~50 tokens (configurable)
   - **Boundary awareness:** Prefer splitting at sentence boundaries
4. For each chunk, generate:
   - Unique chunk ID: `{video_id}-chunk-{sequence_number}`
   - Start/end timestamps (from transcript word-level timing)
   - Full metadata propagation (speaker, title, video_id)
5. Store chunks as individual JSON files in S3: `chunks/{video_id}/chunk-{N}.json`
6. Publish chunk references to SQS for embedding fan-out

**Chunk Schema:**
```json
{
  "chunk_id": "video-123-chunk-001",
  "video_id": "video-123",
  "sequence": 1,
  "text": "The key to building production RAG systems is...",
  "token_count": 487,
  "start_time": 0.0,
  "end_time": 45.2,
  "metadata": {
    "speaker": "Jane Doe",
    "title": "Building RAG Systems",
    "source_s3_key": "uploads/sample.mp4"
  }
}
```

**Output (to Step Functions):**
```json
{
  "statusCode": 200,
  "detail": {
    "chunk_count": 24,
    "chunks_s3_prefix": "chunks/video-123/",
    "chunk_keys": [
      "chunks/video-123/chunk-001.json",
      "chunks/video-123/chunk-002.json"
    ],
    "metadata": { "...propagated..." }
  }
}
```

**Dependencies:** `boto3` (word count is used as a token proxy — no external tokenizer needed)

**Terraform Resources:** Lambda function, IAM role with S3 read/write, SQS send permissions

---

### 7.3 Embedding Module

**Purpose:** Take text chunks, generate vector embeddings using Amazon Bedrock Titan Embeddings V2, and store the vectors in Aurora pgvector.

**Input (from SQS):**
```json
{
  "chunk_s3_key": "chunks/video-123/chunk-001.json"
}
```

**Processing Steps:**

1. Read chunk JSON from S3
2. Extract the text content
3. Call Amazon Bedrock `InvokeModel` with:
   - Model ID: `amazon.titan-embed-text-v2:0`
   - Input text: chunk text
   - Dimensions: 1024 (production) or 256 (workshop/cost-saving)
   - Normalize: true
4. Receive embedding vector (list of floats)
5. Insert into Aurora pgvector:
   ```sql
   INSERT INTO video_chunks (
     chunk_id, video_id, text, embedding,
     speaker, title, start_time, end_time, created_at
   ) VALUES ($1, $2, $3, $4::vector, $5, $6, $7, $8, NOW())
   ON CONFLICT (chunk_id) DO UPDATE SET
     embedding = EXCLUDED.embedding,
     text = EXCLUDED.text;
   ```
6. Return success status

**Output:**
```json
{
  "statusCode": 200,
  "detail": {
    "chunk_id": "video-123-chunk-001",
    "dimensions": 1024,
    "status": "indexed"
  }
}
```

**Error Handling:**

- Bedrock throttling → exponential backoff retry (Step Functions or in-code)
- Aurora connection failures → retry with connection pool refresh
- Batch failures → dead letter queue for failed chunks

**Dependencies:** `boto3`, `psycopg2-binary`, `pgvector`

**Schema Management:** Database migrations are handled separately via Alembic. The embedding module does not manage schema — it assumes tables exist.

**Terraform Resources:** Lambda function (VPC-attached for Aurora access), IAM role with Bedrock InvokeModel and RDS access, Lambda layer for `psycopg2`

---

### 7.4 Question Module (Retrieval Service)

**Purpose:** Accept a natural language question, embed it, perform vector similarity search against pgvector, and return the most relevant chunks. Optionally, pass the chunks to an LLM for answer synthesis.

**Input (HTTP via API Gateway):**
```json
POST /ask
{
  "question": "What did the speaker say about error handling in RAG pipelines?",
  "top_k": 5,
  "filters": {
    "speaker": "Jane Doe"
  }
}
```

**Processing Steps:**

1. Validate input (question must be non-empty, top_k in range 1-20)
2. Generate embedding for the question using Bedrock Titan V2 (same model/dimensions as indexing)
3. Query Aurora pgvector:
   ```sql
   SELECT chunk_id, video_id, text, speaker, title,
          start_time, end_time,
          1 - (embedding <=> $1::vector) AS similarity
   FROM video_chunks
   WHERE ($2::text IS NULL OR speaker = $2)
   ORDER BY embedding <=> $1::vector
   LIMIT $3;
   ```
4. (Optional) Pass retrieved chunks + question to an LLM (Bedrock Claude Haiku) for answer synthesis:
   ```
   Given these transcript excerpts: {chunks}
   Answer this question: {question}
   Cite your sources with timestamps.
   ```
5. Return results

**Output:**
```json
{
  "question": "What did the speaker say about error handling?",
  "answer": "The speaker emphasized three key approaches to error handling...",
  "sources": [
    {
      "chunk_id": "video-123-chunk-012",
      "text": "Error handling in production RAG systems requires...",
      "similarity": 0.89,
      "speaker": "Jane Doe",
      "title": "Building RAG Systems",
      "start_time": 234.5,
      "end_time": 279.8
    }
  ]
}
```

**API Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| POST | `/ask` | Submit a question and get relevant chunks + optional LLM answer |
| GET | `/health` | Health check endpoint |
| GET | `/videos` | List indexed videos |

**Dependencies:** `boto3`, `psycopg2-binary`, `pgvector`, `pydantic`

**Terraform Resources:** Lambda function (VPC-attached), API Gateway REST API, IAM role with Bedrock + RDS access

---

### 7.5 MCP Server

**Purpose:** Expose the question/retrieval service as an MCP (Model Context Protocol) server so that Cursor IDE (or any MCP client) can query video knowledge directly from the IDE.

**MCP Tools Exposed:**

1. **`ask_video_question`** — Submit a question and receive relevant transcript chunks with optional LLM-synthesized answer
   ```
   Tool: ask_video_question
   Input: { "question": "string", "top_k": "int (optional, default 5)" }
   Output: { "answer": "string", "sources": [...] }
   ```

2. **`list_indexed_videos`** — List all videos currently indexed in the system
   ```
   Tool: list_indexed_videos
   Input: {}
   Output: { "videos": [{"video_id": "string", "title": "string", "speaker": "string", "chunk_count": "int"}] }
   ```

3. **`search_by_speaker`** — Search across all content from a specific speaker
   ```
   Tool: search_by_speaker
   Input: { "speaker": "string", "question": "string" }
   Output: { "answer": "string", "sources": [...] }
   ```

**Architecture:**

The MCP server runs locally on the participant's machine and calls the deployed Question Service API (API Gateway endpoint). It does NOT connect directly to Aurora or Bedrock.

```
Cursor IDE ──(stdio)──▶ MCP Server (local Python process) ──(HTTPS)──▶ API Gateway ──▶ Question Lambda
```

**Cursor Configuration (`~/.cursor/mcp.json`):**
```json
{
  "mcpServers": {
    "video-knowledge": {
      "command": "python",
      "args": ["-m", "src.server"],
      "cwd": "<workshop-path>/modules/mcp-server",
      "env": {
        "API_ENDPOINT": "https://<api-gateway-url>/prod"
      }
    }
  }
}
```

**Dependencies:** `mcp[cli]`, `httpx`, `pydantic`

**No Terraform Resources:** Runs locally. Only needs the API Gateway URL from the question module deployment.

---

### 7.6 Step Functions State Machine

**Purpose:** Orchestrate the full pipeline from S3 upload to indexed embeddings.

**State Machine Definition (simplified):**

```
StartState: ValidateInput
  → TranscribeVideo
    → WaitForTranscription (Wait + Poll loop)
      → ChunkTranscript (chunks stored in S3, references published to SQS)
        → SuccessState

SQS Queue → Embedding Lambda (per chunk, independent of Step Functions)

Error paths at each state → ErrorHandler → NotifyFailure
```

**Key Design Decisions:**

- **SQS Fan-Out for Embeddings:** The chunking Lambda publishes chunk references to an SQS queue. The embedding Lambda is triggered by SQS (one invocation per message). This decouples embedding from the Step Functions pipeline, avoids Map state transition costs, and provides built-in retry with dead-letter queue support.
- **Wait Loop for Transcribe:** Use a Choice state + Wait state to poll Transcribe job status every 30 seconds
- **Error Handling:** Each state has a Catch block that routes to a centralized error handler
- **Timeouts:** Overall execution timeout of 60 minutes; individual state timeouts appropriate to each service
- **Input/Output Processing:** Use ResultSelector and OutputPath to keep the state payload lean

**Terraform Resources:** Step Functions state machine, IAM role with Lambda invoke permissions, EventBridge rule for S3 trigger

---

## 8. Infrastructure Design

### 8.1 Aurora Serverless v2 + pgvector Setup

**Database Configuration:**

- Engine: Aurora PostgreSQL 15.x (pgvector compatible)
- Instance class: `db.serverless` (Aurora Serverless v2)
- Min ACU: 0.5 (~$0.06/hr at minimum; does NOT auto-pause to zero)
- Max ACU: 4 (sufficient for workshop load)
- VPC: Default VPC with security group allowing Lambda access
- Public access: Disabled (Lambda connects via VPC)

**Database Schema (managed via Alembic migrations):**

Database schema changes are version-tracked using Alembic, ensuring repeatable and auditable schema evolution across environments.

```sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Main table for video chunks with embeddings
CREATE TABLE video_chunks (
    id SERIAL PRIMARY KEY,
    chunk_id VARCHAR(255) UNIQUE NOT NULL,
    video_id VARCHAR(255) NOT NULL,
    sequence INTEGER NOT NULL,
    text TEXT NOT NULL,
    embedding vector(1024),
    speaker VARCHAR(255),
    title VARCHAR(512),
    start_time FLOAT,
    end_time FLOAT,
    source_s3_key VARCHAR(1024),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Index for vector similarity search (HNSW for better recall)
CREATE INDEX idx_video_chunks_embedding
ON video_chunks USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- Index for metadata filtering
CREATE INDEX idx_video_chunks_video_id ON video_chunks(video_id);
CREATE INDEX idx_video_chunks_speaker ON video_chunks(speaker);

-- Videos metadata table
CREATE TABLE videos (
    video_id VARCHAR(255) PRIMARY KEY,
    title VARCHAR(512),
    speaker VARCHAR(255),
    s3_key VARCHAR(1024),
    duration_seconds FLOAT,
    chunk_count INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'processing',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### 8.2 Networking

- Lambda functions for embedding and question modules must be VPC-attached to access Aurora
- VPC endpoints for S3, Bedrock, and Secrets Manager to allow Lambda-in-VPC to reach AWS services without NAT Gateway
- Security group: Allow PostgreSQL port (5432) inbound only from Lambda security group

### 8.3 IAM Roles (Least Privilege)

**Transcribe Lambda Role:**
- `s3:GetObject` on media bucket
- `s3:PutObject` on transcripts prefix
- `transcribe:StartTranscriptionJob`, `transcribe:GetTranscriptionJob`
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`

**Chunking Lambda Role:**
- `s3:GetObject` on transcripts prefix
- `s3:PutObject` on chunks prefix
- `sqs:SendMessage` on embedding queue
- `logs:*`

**Embedding Lambda Role:**
- `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueAttributes` on embedding queue
- `s3:GetObject` on chunks prefix
- `bedrock:InvokeModel` on Titan Embeddings model
- VPC execution role (`ec2:CreateNetworkInterface`, etc.)
- `logs:*`

**Question Lambda Role:**
- `bedrock:InvokeModel` on Titan Embeddings + Claude Haiku models
- VPC execution role
- `logs:*`

**Step Functions Role:**
- `lambda:InvokeFunction` on all pipeline Lambdas
- `events:PutEvents` for EventBridge
- `logs:*`

### 8.4 Terraform Module Map

```
infra/
├── bootstrap/
│   └── main.tf                    # S3 bucket + DynamoDB for TF state
├── environments/dev/
│   ├── main.tf                    # Composes all modules below
│   ├── variables.tf               # Environment-specific vars
│   ├── outputs.tf                 # API URLs, bucket names, etc.
│   ├── providers.tf               # AWS provider config
│   └── deploy.sh                  # Build + deploy script
└── modules/
    ├── s3/                        # Media + transcripts + chunks buckets
    ├── lambda/                    # Generic Lambda (transcribe, chunking)
    ├── lambda-vpc/                # VPC-attached Lambda (embedding, question)
    ├── aurora-vectordb/           # Aurora Serverless v2 + pgvector + schema init
    ├── step-functions/            # State machine + EventBridge trigger
    ├── sqs/                       # SQS queues for fan-out
    ├── api-gateway/               # REST API for question service
    ├── networking/                # VPC endpoints, security groups
    └── secrets/                   # Secrets Manager for DB credentials
```

---

## 9. Workshop Stages & RIPER-5 Mapping

Each workshop stage follows the RIPER-5 protocol. The instructor guides participants through each mode for every stage. Spec files in `specs/prompts/` provide the detailed specification for each stage.

### Stage 1: Introduction & Architecture Overview (45 min)

**Mode: RESEARCH**

- Present the reference architecture and data flow diagram
- Walk through the project structure and module boundaries
- Explain the EventBridge event format and Lambda response format
- Discuss the technology choices and trade-offs (Bedrock vs OpenAI, pgvector vs Pinecone)
- Review the RIPER-5 development methodology

**No code is written.** Participants read, ask questions, and build shared understanding.

**Artifacts produced:**
- Shared understanding of the architecture
- Local repo cloned and explored
- AWS credentials verified (`aws sts get-caller-identity`)

---

### Stage 2: Video Upload & Workflow Trigger (45 min)

**Spec file:** `specs/prompts/1-s3-upload-trigger.md`

| RIPER Phase | Activity | Duration |
|-------------|----------|----------|
| RESEARCH | Explore S3 event patterns, S3 EventBridge notifications, EventBridge rules | 10 min |
| INNOVATE | Discuss trigger options: S3 legacy notifications vs S3→EventBridge (direct) vs direct Lambda trigger | 5 min |
| PLAN | Define Terraform resources: S3 bucket with EventBridge notifications, EventBridge rule, target Step Functions | 10 min |
| EXECUTE | Write Terraform for S3 + trigger infrastructure; test with a sample upload | 15 min |
| REVIEW | Verify event reaches Step Functions; inspect CloudWatch logs | 5 min |

**Deliverable:** Uploading a file to `s3://<bucket>/uploads/` triggers the Step Functions state machine.

---

### Stage 3: Transcription with AWS Transcribe (90 min)

**Spec file:** `specs/prompts/2-transcription.md`

| RIPER Phase | Activity | Duration |
|-------------|----------|----------|
| RESEARCH | Study AWS Transcribe API, async job model, output format, word-level timestamps | 15 min |
| INNOVATE | Discuss: polling vs callback for job completion; output format choices; language detection | 10 min |
| PLAN | Define handler, service layer, Step Functions states (start job, wait loop, check status), Terraform | 15 min |
| EXECUTE | Implement transcribe module: handler, service, tests (moto mocks); deploy Lambda; wire into Step Functions | 40 min |
| REVIEW | Upload sample video, watch Step Functions execution graph, inspect transcript in S3 | 10 min |

**Deliverable:** A video uploaded to S3 is automatically transcribed; raw transcript JSON appears in `s3://<bucket>/transcripts/`.

---

### Stage 4: Chunking & Queue-Based Fan-Out (75 min)

**Spec file:** `specs/prompts/3-chunking.md`

| RIPER Phase | Activity | Duration |
|-------------|----------|----------|
| RESEARCH | Study chunking strategies (fixed-size, sentence-boundary, semantic); review token counting | 10 min |
| INNOVATE | Discuss: chunk size trade-offs (retrieval precision vs context); overlap strategies; metadata design | 10 min |
| PLAN | Define chunking algorithm, chunk schema, S3 output structure, SQS fan-out, Step Functions integration | 10 min |
| EXECUTE | Implement chunking module: handler, chunking service, chunk model, tests; deploy; wire into Step Functions | 35 min |
| REVIEW | Run pipeline end-to-end through chunking; verify chunks in S3; inspect chunk metadata | 10 min |

**Deliverable:** Transcripts are chunked into ~500-token segments with timestamps and metadata, stored in S3 and ready for embedding.

---

### Stage 5: Embedding & Vector Storage (75 min)

**Spec file:** `specs/prompts/4-embedding.md`

| RIPER Phase | Activity | Duration |
|-------------|----------|----------|
| RESEARCH | Study Bedrock Titan Embeddings V2 API; pgvector query syntax; HNSW vs IVFFlat indexes | 10 min |
| INNOVATE | Discuss: embedding dimensions trade-off (256 vs 1024); batch vs per-chunk processing; index type selection | 10 min |
| PLAN | Define embedding service (Bedrock client), pgvector insert logic, Aurora schema, VPC networking, SQS trigger | 10 min |
| EXECUTE | Deploy Aurora Serverless v2 + pgvector (Terraform); implement embedding module; Lambda layer for psycopg2; test with sample chunks | 35 min |
| REVIEW | Query pgvector directly (psql or Lambda test) to verify embeddings stored; check vector dimensions and similarity search works | 10 min |

**Deliverable:** Text chunks are embedded via Bedrock and stored in Aurora pgvector. A direct SQL similarity query returns relevant results.

---

### Stage 6: Building the Retrieval / Question Service (75 min)

**Spec file:** `specs/prompts/5-question-service.md`

| RIPER Phase | Activity | Duration |
|-------------|----------|----------|
| RESEARCH | Study the question flow: embed query → vector search → (optional) LLM synthesis; review API Gateway setup | 10 min |
| INNOVATE | Discuss: RAG vs pure retrieval; re-ranking strategies; filter design; response format | 10 min |
| PLAN | Define API contract (OpenAPI spec), question handler, retrieval service, Bedrock LLM integration, API Gateway Terraform | 10 min |
| EXECUTE | Implement question module: handler, retrieval service, API endpoint; deploy API Gateway + Lambda; test with curl/Postman | 35 min |
| REVIEW | Send sample questions via API; verify relevant chunks are returned; test with different queries and filters | 10 min |

**Deliverable:** A REST API at `POST /ask` accepts natural language questions and returns relevant video transcript chunks with similarity scores.

---

### Stage 7: MCP Server & Cursor Integration (60 min)

**Spec file:** `specs/prompts/6-mcp-server.md`

| RIPER Phase | Activity | Duration |
|-------------|----------|----------|
| RESEARCH | Study MCP protocol basics; review mcp Python SDK; understand stdio transport | 10 min |
| INNOVATE | Discuss: which tools to expose; how MCP fits into agentic architectures; context vs tools | 5 min |
| PLAN | Define MCP tool schemas; map to Question Service API calls; plan Cursor config | 10 min |
| EXECUTE | Implement MCP server with 2-3 tools; configure Cursor `mcp.json`; test in Cursor chat | 25 min |
| REVIEW | Demo querying video knowledge from Cursor; verify tool responses; test edge cases | 10 min |

**Deliverable:** Cursor IDE can query the video knowledge base directly. Asking "What did the speaker say about error handling?" in Cursor returns relevant transcript excerpts.

---

### Stage 8: Wrap-Up — Production Concerns & Next Steps (30 min)

**Mode: RESEARCH + INNOVATE (discussion-only)**

Topics covered:
- **Observability:** Step Functions execution history, CloudWatch dashboards, structured logging
- **Reprocessing:** How to re-run failed embeddings; idempotency via `ON CONFLICT`
- **Security:** IAM least privilege review; VPC isolation; data encryption
- **Cost optimization:** Aurora auto-pause; Bedrock vs self-hosted embeddings at scale; S3 lifecycle policies
- **Scaling:** pgvector HNSW tuning; Lambda concurrency limits; SQS batching
- **Extensions:**
  - Multi-modal RAG (slides + audio + video frames)
  - Summarization pipeline
  - Re-indexing workflows
  - Evaluation frameworks (RAGAS, etc.)
  - Agent-to-agent communication via MCP

**Deliverable:** Participants have a clear roadmap for evolving the workshop system into production.

---

## 10. Cost Analysis

### 10.0 Assumptions

- **Videos:** 10 videos, 50 minutes each (500 minutes total audio)
- **Infrastructure lifetime:** 3 days (72 hours) — deployed morning of workshop, destroyed end of day 3
- **Active workshop:** 1 day (~8 hours of active use)
- **Idle time:** ~64 hours (overnight + 2 extra days before teardown)
- **Region:** us-east-1
- **Chunking estimate:** ~150 words/min × 500 min = 75,000 words ≈ 100,000 tokens → ~200 chunks at 500 tokens each
- **Query testing:** ~50 questions asked during workshop

### 10.1 Per-Participant Cost Breakdown (3-Day Infrastructure Lifetime)

#### Compute & Orchestration

| Service | Usage Calculation | Cost |
|---------|-------------------|------|
| Lambda | ~320 invocations (10 transcribe starts + 50 polls + 10 chunk + 200 embed + 50 query), ~1,200s at 256MB | $0.01 |
| Step Functions | 10 executions × ~15 base transitions = ~150 transitions (embeddings handled by SQS, not Step Functions) | $0.00 |
| EventBridge | ~100 events | $0.00 |

**Subtotal: ~$0.01**

#### AI & ML Services

| Service | Usage Calculation | Cost |
|---------|-------------------|------|
| **AWS Transcribe** | **10 videos × 50 min = 500 min @ $0.024/min** | **$12.00** |
| Bedrock Titan Embeddings V2 | ~101K tokens (200 chunks × 500 tokens + 50 queries × 20 tokens) @ $0.02/M tokens | $0.002 |
| Bedrock Claude Haiku (answer synthesis) | ~126K input tokens + ~10K output tokens @ $0.25/$1.25 per M tokens | $0.05 |

**Subtotal: ~$12.05**

#### Storage & Messaging

| Service | Usage Calculation | Cost |
|---------|-------------------|------|
| S3 | ~1.5 GB (videos + transcripts + chunks) × 3 days, ~2.5K requests | $0.01 |
| SQS | ~500 messages (chunk fan-out + polling) | $0.00 |
| Secrets Manager | 1 secret (DB creds) × 3 days | $0.04 |

**Subtotal: ~$0.05**

#### Database (Aurora Serverless v2 + pgvector)

| Component | Usage Calculation | Cost |
|-----------|-------------------|------|
| **Aurora compute** | **0.5 ACU minimum × 72 hrs + burst to ~1 ACU during 8 hrs active use = ~40 ACU-hours @ $0.12/ACU-hr** | **$4.80** |
| Aurora storage | ~100 MB (200 chunks × 1024-dim vectors + metadata) @ $0.10/GB/mo | $0.00 |
| Aurora I/O | ~5K I/O requests @ $0.20/M | $0.00 |

**Subtotal: ~$4.80**

> **Important:** Aurora Serverless v2 does NOT auto-pause to zero. It scales down to a minimum of 0.5 ACU ($0.06/hr) but keeps running 24/7. This is the second-largest cost and is entirely driven by the 72-hour lifetime. Tearing down at end of workshop day 1 instead of day 3 would reduce this from $4.80 to $0.96.

#### Networking

| Component | Usage Calculation | Cost |
|-----------|-------------------|------|
| S3 Gateway Endpoint | Free (gateway endpoints have no hourly charge) | $0.00 |
| **Bedrock Runtime Interface Endpoint** | **1 AZ × 72 hrs @ $0.01/hr** | **$0.72** |
| **Secrets Manager Interface Endpoint** | **1 AZ × 72 hrs @ $0.01/hr** | **$0.72** |
| VPC Endpoint data processing | ~1 GB @ $0.01/GB | $0.01 |

**Subtotal: ~$1.45**

> VPC Interface Endpoints are required because the embedding and question Lambdas run inside a VPC (to reach Aurora) and need a path to Bedrock and Secrets Manager. The S3 Gateway Endpoint is free. An alternative is a NAT Gateway ($0.045/hr = $3.24 for 72 hrs + data charges), which is more expensive.

#### Monitoring

| Component | Usage Calculation | Cost |
|-----------|-------------------|------|
| CloudWatch Logs | ~50 MB ingestion @ $0.50/GB | $0.03 |
| CloudWatch Metrics | Standard Lambda/Aurora metrics (free tier) | $0.00 |

**Subtotal: ~$0.03**

---

#### Total Per-Participant Cost

| Category | Cost | % of Total |
|----------|------|------------|
| AI & ML (Transcribe + Bedrock) | $12.05 | **65%** |
| Database (Aurora Serverless v2) | $4.80 | **26%** |
| Networking (VPC Endpoints) | $1.45 | **8%** |
| Everything else | $0.09 | 1% |
| **Total per participant** | **~$18.39** | **100%** |

---

### 10.2 Cost Sensitivity Analysis

The three cost drivers are Transcribe (65%), Aurora (26%), and VPC Endpoints (8%). Here is how the total changes under different assumptions:

| Scenario | Transcribe | Aurora | VPC | Other | Total |
|----------|-----------|--------|-----|-------|-------|
| **Baseline** (10×50min, 72hr infra) | $12.00 | $4.80 | $1.45 | $0.09 | **$18.39** |
| Teardown same day (10×50min, 10hr infra) | $12.00 | $0.96 | $0.20 | $0.09 | **$13.25** |
| Fewer/shorter videos (5×10min, 72hr infra) | $1.20 | $4.80 | $1.45 | $0.09 | **$7.54** |
| Pre-transcribed videos (skip Transcribe) | $0.00 | $4.80 | $1.45 | $0.09 | **$6.34** |
| Pre-transcribed + same-day teardown | $0.00 | $0.96 | $0.20 | $0.09 | **$1.25** |
| 256-dim embeddings (smaller vectors) | $12.00 | $4.80 | $1.45 | $0.09 | $18.34 (minimal saving) |

### 10.3 Cost-Saving Strategies

**High Impact:**

1. **Pre-transcribe videos:** Provide transcript JSON files in the workshop repo. Participants still *implement* the transcribe module and can run it on a short clip to verify, but the 10 full-length transcripts are pre-computed on your account. **Saves $12.00/participant** (65% of total cost).

2. **Same-day teardown:** End the workshop with a guided `terraform destroy`. Reducing infra lifetime from 72 hours to ~10 hours **saves $4.85/participant** (Aurora + VPC endpoints idle time).

3. **Combine both:** Pre-transcribe + same-day teardown brings cost to **~$1.25/participant**. For 30 participants = ~$37.50 total.

**Medium Impact:**

4. **Use fewer/shorter sample videos:** 5 videos at 10 minutes each instead of 10 at 50 minutes. Reduces Transcribe cost from $12.00 to $1.20.

5. **Use 256-dimension embeddings:** Slightly reduces Aurora storage and Bedrock token overhead, but savings are negligible (<$0.05). Main benefit is faster search, not cost.

6. **Share Aurora cluster:** If using AWS Workshop Studio or a shared account, a single Aurora cluster for all participants reduces the per-person database cost. One cluster at 2 ACU handles 30 concurrent users easily. Cost: $0.24/hr × 10 hrs = $2.40 total (vs $4.80 × 30 = $144 for individual clusters).

**Low Impact (but good practice):**

7. **Region selection:** `us-east-1` has the best pricing for Bedrock and Transcribe.
8. **S3 lifecycle policies:** Auto-delete uploaded videos after 3 days.
9. **Lambda right-sizing:** 256 MB is sufficient for all modules; don't over-allocate.

### 10.4 Budget Scenarios

| Scenario | Participants | Per-Person | Total Cost |
|----------|-------------|-----------|------------|
| Full pipeline, 3-day infra | 30 | $18.39 | **~$552** |
| Full pipeline, same-day teardown | 30 | $13.25 | **~$398** |
| Pre-transcribed, 3-day infra | 30 | $6.34 | **~$190** |
| Pre-transcribed, same-day teardown | 30 | $1.25 | **~$38** |
| Shared Aurora + pre-transcribed | 30 | ~$0.50 | **~$15** |
| AWS-sponsored workshop accounts | 30 | $0.00 | **$0** (to you) |
| Dry run / rehearsal | 1 | $18.39 | **~$18** |

### 10.5 Recommended Approach

Given the need to manage costs with uncertain funding:

1. **Pre-transcribe the 10 videos** on your own account ($12 one-time cost). Include transcript JSONs in the repo. Participants implement and test the transcribe module on a 2-minute clip, then use the pre-built transcripts for the rest of the pipeline.

2. **End the workshop with a guided teardown.** Walk through `terraform destroy` as part of Stage 8 (Wrap-Up). This is both a cost-saving measure and a production best practice to teach.

3. **If funding is secured:** Let participants run full transcription on all 10 videos. The experience of watching the Step Functions graph execute in real-time is worth the ~$12/person.

4. **Target budget: $40-200** depending on whether transcription is live or pre-computed.

---

## 11. Deliverables & Success Criteria

### 11.1 End-of-Day Deliverables

Each participant will have:

1. **A working end-to-end video ingestion pipeline** — Upload a video, get it transcribed, chunked, embedded, and indexed automatically
2. **A semantic search REST API** — Query video content with natural language and receive relevant, ranked results
3. **An MCP server integrated with Cursor** — Ask questions about video content directly from the IDE
4. **Infrastructure as Code** — All AWS resources defined in Terraform, reproducible and destroyable
5. **Reference specs and code patterns** — Spec files for every module, usable as templates for future projects

### 11.2 Success Criteria

| Criterion | Verification Method |
|-----------|-------------------|
| Video upload triggers Step Functions | Upload sample.mp3 → verify execution starts in SF console |
| Transcription completes automatically | Check S3 for `transcripts/{video_id}/raw.json` |
| Chunking produces valid chunks | Check S3 for `chunks/{video_id}/` directory with JSON files |
| Embeddings stored in pgvector | Query `SELECT count(*) FROM video_chunks WHERE video_id = 'xxx'` |
| Semantic search returns relevant results | `curl POST /ask` with a question → verify non-empty, relevant response |
| MCP server responds in Cursor | Ask a question in Cursor chat → verify tool invocation and response |
| All infrastructure is Terraform-managed | `terraform plan` shows no drift |
| Cleanup works | `terraform destroy` removes all resources |

### 11.3 Stretch Goals (if time permits)

- Add a CloudWatch dashboard for pipeline observability
- Implement re-ranking with a cross-encoder model
- Add a simple web UI for the question service
- Configure CI/CD with GitHub Actions (reference exists in video-pipeline repo)

---

## 12. Risk Assessment & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Bedrock model access not enabled** | High | Blocks embedding + question stages | Pre-workshop checklist; verify `aws bedrock list-foundation-models` works; have backup instructions |
| **Aurora Serverless v2 cold start** | Medium | 30-60s delay on first query after pause | Pre-warm Aurora 15 min before embedding stage; set auto-pause timeout to 30 min during workshop |
| **VPC networking issues** | Medium | Lambda can't reach Aurora | Provide pre-built Terraform networking module; test thoroughly; have fallback to RDS public access (dev only) |
| **AWS service quotas** | Low | Lambda concurrency, Bedrock throttling | Request quota increases pre-workshop; limit Step Functions Map concurrency to 5 |
| **Participant AWS account issues** | Medium | Can't deploy infrastructure | Provide detailed setup guide; have 2-3 backup accounts; pair participants if needed |
| **Terraform state conflicts** | Low | Deployment failures | Each participant uses unique prefix/workspace; bootstrap script handles state isolation |
| **Sample video too long** | Low | Transcription takes too long, costs more | Cap sample videos at 5-10 minutes; provide pre-transcribed fallback data |
| **WiFi/network issues at venue** | Medium | Can't deploy or call AWS APIs | Provide pre-built artifacts for each stage; allow offline code review and testing with mocks |
| **Time overrun on early stages** | Medium | Later stages get compressed | Provide checkpoint repos for each stage; participants can fast-forward if needed |
| **psycopg2 Lambda layer issues** | Medium | Embedding/question Lambdas fail | Pre-build and test Lambda layer; provide fallback with `psycopg2-binary` |

### 12.1 Contingency: Stage Checkpoints

For each stage, provide a Git branch or tagged release that contains the completed state. If a participant falls behind, they can `git checkout stage-N` and continue from there.

```
git checkout stage-0-scaffold      # Empty project structure
git checkout stage-1-s3-trigger    # S3 + EventBridge + Step Functions trigger
git checkout stage-2-transcribe    # + Transcription module
git checkout stage-3-chunking      # + Chunking module
git checkout stage-4-embedding     # + Embedding module + Aurora
git checkout stage-5-question      # + Question service + API Gateway
git checkout stage-6-mcp           # + MCP server
git checkout stage-7-complete      # Full system
```

---

## 13. Appendices

### Appendix A: AWS Services Quick Reference

| Service | Documentation | Key API Calls |
|---------|--------------|---------------|
| S3 | [docs](https://docs.aws.amazon.com/s3/) | `PutObject`, `GetObject` |
| Transcribe | [docs](https://docs.aws.amazon.com/transcribe/) | `StartTranscriptionJob`, `GetTranscriptionJob` |
| Bedrock | [docs](https://docs.aws.amazon.com/bedrock/) | `InvokeModel` (titan-embed-text-v2, claude-3-haiku) |
| Aurora PostgreSQL | [docs](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/) | Standard PostgreSQL + pgvector |
| Step Functions | [docs](https://docs.aws.amazon.com/step-functions/) | `StartExecution`, state machine definition |
| EventBridge | [docs](https://docs.aws.amazon.com/eventbridge/) | `PutRule`, `PutTargets` |
| SQS | [docs](https://docs.aws.amazon.com/sqs/) | `SendMessage`, `ReceiveMessage` |
| API Gateway | [docs](https://docs.aws.amazon.com/apigateway/) | REST API configuration |
| Lambda | [docs](https://docs.aws.amazon.com/lambda/) | Function configuration, layers |

### Appendix B: pgvector Quick Reference

```sql
-- Create extension
CREATE EXTENSION vector;

-- Create table with vector column
CREATE TABLE items (id serial, embedding vector(1024));

-- Insert vector
INSERT INTO items (embedding) VALUES ('[0.1, 0.2, ...]'::vector);

-- Cosine similarity search (lower distance = more similar)
SELECT *, 1 - (embedding <=> query_vector) AS similarity
FROM items
ORDER BY embedding <=> query_vector
LIMIT 5;

-- Euclidean distance search
SELECT * FROM items ORDER BY embedding <-> query_vector LIMIT 5;

-- Create HNSW index (recommended for < 1M vectors)
CREATE INDEX ON items USING hnsw (embedding vector_cosine_ops);

-- Create IVFFlat index (for > 1M vectors)
CREATE INDEX ON items USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

### Appendix C: Bedrock Titan Embeddings V2 API

```python
import boto3
import json

bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

response = bedrock.invoke_model(
    modelId="amazon.titan-embed-text-v2:0",
    contentType="application/json",
    accept="application/json",
    body=json.dumps({
        "inputText": "Your text to embed here",
        "dimensions": 1024,    # 256, 512, or 1024
        "normalize": True
    })
)

result = json.loads(response["body"].read())
embedding = result["embedding"]    # List of floats
token_count = result["inputTextTokenCount"]
```

### Appendix D: MCP Server Skeleton

```python
from mcp.server import Server
from mcp.types import Tool, TextContent
import httpx

app = Server("video-knowledge")

@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="ask_video_question",
            description="Ask a question about indexed video content",
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results",
                        "default": 5
                    }
                },
                "required": ["question"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "ask_video_question":
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{API_ENDPOINT}/ask",
                json=arguments
            )
            return [TextContent(type="text", text=response.text)]
```

### Appendix E: Cleanup Script

```bash
#!/bin/bash
# cleanup.sh - Run after workshop to destroy all resources

echo "Destroying workshop infrastructure..."
cd infra/environments/dev

terraform destroy -auto-approve

echo "Removing S3 state bucket (manual step)..."
echo "Run: aws s3 rb s3://<state-bucket> --force"

echo "Cleanup complete. Verify in AWS Console that no resources remain."
```

### Appendix F: Glossary

| Term | Definition |
|------|-----------|
| **RAG** | Retrieval-Augmented Generation — augmenting LLM responses with retrieved context from a knowledge base |
| **Embedding** | A dense vector representation of text that captures semantic meaning |
| **Vector Database** | A database optimized for storing and querying high-dimensional vectors by similarity |
| **pgvector** | A PostgreSQL extension for vector similarity search |
| **HNSW** | Hierarchical Navigable Small World — an approximate nearest neighbor algorithm used for fast vector search |
| **MCP** | Model Context Protocol — a protocol for connecting AI models to external tools and data sources |
| **Step Functions** | AWS service for orchestrating multi-step serverless workflows as state machines |
| **EventBridge** | AWS service for event-driven architectures; routes events between AWS services |
| **Chunking** | Splitting large text into smaller segments optimized for embedding and retrieval |
| **Cosine Similarity** | A measure of similarity between two vectors based on the cosine of the angle between them (1 = identical, 0 = orthogonal) |
| **ACU** | Aurora Capacity Unit — billing unit for Aurora Serverless compute capacity |
| **RIPER-5** | Research, Innovate, Plan, Execute, Review — a structured protocol for AI-assisted development |

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-02-26 | Wesley Reisz | Initial PRD |
