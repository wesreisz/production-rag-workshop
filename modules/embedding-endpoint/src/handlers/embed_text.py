import json
import os

import boto3

bedrock = boto3.client("bedrock-runtime")
dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", "256"))
api_key = os.environ.get("API_KEY", "")


def handler(event, context):
    try:
        headers = event.get("headers", {})
        provided_key = headers.get("x-api-key", "")
        if not api_key or provided_key != api_key:
            return _response(401, {"error": "unauthorized"})

        body = event.get("body", "{}")
        if isinstance(body, str):
            body = json.loads(body)

        text = body.get("text", "").strip() if isinstance(body.get("text"), str) else ""
        if not text:
            return _response(400, {"error": "text field is required"})

        response = bedrock.invoke_model(
            modelId="amazon.titan-embed-text-v2:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "inputText": text,
                "dimensions": dimensions,
                "normalize": True,
            }),
        )
        result = json.loads(response["body"].read())

        return _response(200, {
            "embedding": result["embedding"],
            "dimensions": dimensions,
            "model": "amazon.titan-embed-text-v2:0",
        })
    except Exception as exc:
        return _response(500, {"error": str(exc)})


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }
