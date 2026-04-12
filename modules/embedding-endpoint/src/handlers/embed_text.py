import json
import os

import boto3

_bedrock = boto3.client("bedrock-runtime")
_api_key = os.environ.get("API_KEY", "")
if not _api_key:
    raise ValueError("API_KEY environment variable must be set")
_dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", "256"))

_CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": _CORS_HEADERS,
        "body": json.dumps(body),
    }


def handler(event, context):
    headers = event.get("headers") or {}
    if headers.get("x-api-key") != _api_key:
        return _response(401, {"error": "unauthorized"})

    raw_body = event.get("body")
    if not raw_body:
        return _response(400, {"error": "body is required"})

    try:
        body = json.loads(raw_body)
    except (json.JSONDecodeError, TypeError):
        return _response(400, {"error": "body must be valid JSON"})

    text = body.get("text")
    if not text or not text.strip():
        return _response(400, {"error": "text field is required"})

    try:
        response = _bedrock.invoke_model(
            modelId="amazon.titan-embed-text-v2:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "inputText": text,
                "dimensions": _dimensions,
                "normalize": True,
            }),
        )
        result = json.loads(response["body"].read())
    except Exception:
        return _response(500, {"error": "internal error"})

    return _response(200, {
        "embedding": result["embedding"],
        "dimensions": _dimensions,
        "model": "amazon.titan-embed-text-v2:0",
    })
