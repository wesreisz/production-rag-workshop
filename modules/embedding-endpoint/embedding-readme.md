# Embedding Endpoint

A public HTTPS Lambda endpoint that generates 256-dimensional embedding vectors using Amazon Bedrock Titan Text Embeddings V2. Workshop participants use this to generate embeddings for pgvector similarity queries in the RDS Query Editor.

## Setup

After `terraform apply`, get the endpoint URL and API key:

```bash
cd infra/environments/dev
EMBED_URL=$(terraform output -raw embed_text_endpoint_url)
API_KEY=$(terraform output -raw embed_text_api_key)
```

## Generate an Embedding

```bash
curl -s -X POST "$EMBED_URL" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d '{"text": "What did Wes talk about?"}' | python3 -m json.tool
```

To copy just the embedding array to your clipboard (macOS):

```bash
curl -s -X POST "$EMBED_URL" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d '{"text": "What did Wes talk about?"}' | jq -r '.embedding' | pbcopy
```

## Similarity Search in RDS Query Editor

Paste the embedding into a query using a CTE so you only paste it once:

```sql
WITH query AS (
  SELECT '<paste_embedding_here>'::vector AS embedding
)
SELECT chunk_id, left(text, 80) AS text_preview,
       1 - (v.embedding <=> q.embedding) AS similarity
FROM video_chunks v, query q
ORDER BY v.embedding <=> q.embedding
LIMIT 5;
```

Results are sorted by cosine similarity (closer to 1 = more similar).

## API Reference

**Request:**

```
POST <EMBED_URL>
Content-Type: application/json
x-api-key: <API_KEY>

{"text": "your text here"}
```

**Response (200):**

```json
{
  "embedding": [0.0123, -0.0456, ...],
  "dimensions": 256,
  "model": "amazon.titan-embed-text-v2:0"
}
```

**Errors:**

| Status | Body | Cause |
|--------|------|-------|
| 401 | `{"error": "unauthorized"}` | Missing or invalid `x-api-key` header |
| 400 | `{"error": "text field is required"}` | Missing or empty `text` field |
| 500 | `{"error": "<message>"}` | Bedrock invocation failure |
