# Embedding Endpoint

A public HTTPS endpoint that generates 256-dimensional embeddings via Amazon Bedrock Titan Text Embeddings V2. Use this during the workshop to generate embeddings interactively and run similarity searches against pgvector.

## Get the URL and API key

```bash
cd infra/environments/dev
EMBED_URL=$(terraform output -raw embed_text_endpoint_url)
API_KEY=$(terraform output -raw embed_text_api_key)
```

## Generate an embedding

```bash
curl -s -X POST "$EMBED_URL" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d '{"text": "What did Wes talk about?"}' | python3 -m json.tool
```

Expected response:

```json
{
  "embedding": [0.0123, -0.0456, ...],
  "dimensions": 256,
  "model": "amazon.titan-embed-text-v2:0"
}
```

## Use the embedding for similarity search

1. Copy the `embedding` array from the curl response
2. Open the AWS Console → RDS → Query Editor
3. Connect to `production-rag-vectordb` / `ragdb` using the Secrets Manager secret ARN
4. Run:

```sql
SELECT chunk_id, left(text, 80) AS text_preview,
       1 - (embedding <=> '<paste_embedding_here>'::vector) AS similarity
FROM video_chunks
ORDER BY embedding <=> '<paste_embedding_here>'::vector
LIMIT 5;
```

Or use the AWS CLI Data API:

```bash
SECRET_ARN=$(terraform output -raw aurora_secret_arn)
CLUSTER_ARN=$(aws rds describe-db-clusters \
  --query "DBClusters[?contains(DBClusterIdentifier,'production-rag')].DBClusterArn" \
  --output text)

EMBEDDING=$(curl -s -X POST "$EMBED_URL" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d '{"text": "What did Wes talk about?"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['embedding'])")

aws rds-data execute-statement \
  --resource-arn "$CLUSTER_ARN" \
  --secret-arn "$SECRET_ARN" \
  --database "ragdb" \
  --sql "SELECT chunk_id, left(text, 80) FROM video_chunks ORDER BY embedding <=> '$EMBEDDING'::vector LIMIT 5;"
```

## Error responses

| Status | Body | Cause |
|--------|------|-------|
| 401 | `{"error": "unauthorized"}` | Missing or wrong `x-api-key` header |
| 400 | `{"error": "text field is required"}` | Missing or empty `text` in body |
| 400 | `{"error": "body is required"}` | No request body |
| 500 | `{"error": "internal error"}` | Bedrock failure |
