import json
import os

import boto3

from src.services.retrieval_service import service
from src.utils.logger import get_logger

logger = get_logger(__name__)

s3_client = boto3.client("s3")
MEDIA_BUCKET = os.environ.get("MEDIA_BUCKET", "")


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def _parse_post_body(event):
    raw_body = event.get("body") or "{}"
    return json.loads(raw_body)


def _validate_ask_params(body):
    question = body.get("question", "")
    if not question or not str(question).strip():
        return None, _response(400, {"error": "question is required"})

    top_k = body.get("top_k", 5)
    if not isinstance(top_k, int) or top_k < 1 or top_k > 100:
        return None, _response(400, {"error": "top_k must be between 1 and 100"})

    similarity_threshold = body.get("similarity_threshold", 0.0)
    if not isinstance(similarity_threshold, (int, float)) or similarity_threshold < 0.0 or similarity_threshold > 1.0:
        return None, _response(400, {"error": "similarity_threshold must be between 0.0 and 1.0"})

    return {
        "question": question,
        "top_k": top_k,
        "similarity_threshold": float(similarity_threshold),
    }, None


def _handle_presign(event):
    video_id = (event.get("pathParameters") or {}).get("video_id")
    chunk_id = (event.get("queryStringParameters") or {}).get("chunk_id")

    if chunk_id:
        metadata = service.get_chunk_metadata(chunk_id)
        if metadata is None:
            return _response(404, {"error": "chunk not found"})
        presigned_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": MEDIA_BUCKET, "Key": metadata["source_s3_key"]},
            ExpiresIn=3600,
        )
        return _response(200, {
            "video_id": metadata["video_id"],
            "presigned_url": presigned_url,
            "expires_in": 3600,
            "source_s3_key": metadata["source_s3_key"],
            "speaker": metadata["speaker"],
            "title": metadata["title"],
            "start_time": metadata["start_time"],
            "end_time": metadata["end_time"],
        })

    metadata = service.get_video_metadata(video_id)
    if metadata is None:
        return _response(404, {"error": "video not found"})
    presigned_url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": MEDIA_BUCKET, "Key": metadata["source_s3_key"]},
        ExpiresIn=3600,
    )
    return _response(200, {
        "video_id": video_id,
        "presigned_url": presigned_url,
        "expires_in": 3600,
        "source_s3_key": metadata["source_s3_key"],
        "speaker": metadata["speaker"],
        "title": metadata["title"],
    })


def handler(event, context):
    resource = event.get("resource", "")
    method = event.get("httpMethod", "")

    try:
        if method == "GET" and resource == "/health":
            return _response(200, {"status": "healthy"})

        if method == "GET" and resource == "/videos":
            videos = service.list_videos()
            return _response(200, {"videos": videos})

        if method == "POST" and resource == "/ask":
            body = _parse_post_body(event)
            params, err = _validate_ask_params(body)
            if err:
                return err
            speaker = (body.get("filters") or {}).get("speaker")
            embedding = service.generate_embedding(params["question"])
            results = service.search_similar(
                embedding,
                params["top_k"],
                params["similarity_threshold"],
                speaker=speaker,
            )
            return _response(200, {"question": params["question"], "results": results})

        if method == "POST" and resource == "/videos/{video_id}/ask":
            video_id = (event.get("pathParameters") or {}).get("video_id")
            body = _parse_post_body(event)
            params, err = _validate_ask_params(body)
            if err:
                return err
            embedding = service.generate_embedding(params["question"])
            results = service.search_similar(
                embedding,
                params["top_k"],
                params["similarity_threshold"],
                video_id=video_id,
            )
            return _response(200, {
                "video_id": video_id,
                "question": params["question"],
                "results": results,
            })

        if method == "GET" and resource == "/videos/{video_id}/presign":
            return _handle_presign(event)

        return _response(404, {"error": "not found"})

    except Exception:
        logger.exception("Unhandled error in question handler")
        return _response(500, {"error": "internal error"})
