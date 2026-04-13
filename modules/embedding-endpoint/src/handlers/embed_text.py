import json
import os

import boto3

bedrock_client = boto3.client("bedrock-runtime")
API_KEY = os.environ["API_KEY"]
DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "256"))

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}


def handler(event, context):
    headers = event.get("headers", {})
    api_key = headers.get("x-api-key")

    if not api_key or api_key != API_KEY:
        return {
            "statusCode": 401,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": "unauthorized"}),
        }

    try:
        body = json.loads(event.get("body", "{}"))
    except (json.JSONDecodeError, TypeError):
        return {
            "statusCode": 400,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": "text field is required"}),
        }

    text = body.get("text")
    if not text:
        return {
            "statusCode": 400,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": "text field is required"}),
        }

    try:
        response = bedrock_client.invoke_model(
            modelId="amazon.titan-embed-text-v2:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "inputText": text,
                "dimensions": DIMENSIONS,
                "normalize": True,
            }),
        )
        result = json.loads(response["body"].read())
        embedding = result["embedding"]
    except Exception:
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": "internal error"}),
        }

    return {
        "statusCode": 200,
        "headers": CORS_HEADERS,
        "body": json.dumps({
            "embedding": embedding,
            "dimensions": DIMENSIONS,
            "model": "amazon.titan-embed-text-v2:0",
        }),
    }
