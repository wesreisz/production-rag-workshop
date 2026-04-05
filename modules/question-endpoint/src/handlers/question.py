import json

from src.services.retrieval_service import service
from src.utils.logger import get_logger

logger = get_logger(__name__)


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

        return _response(404, {"error": "not found"})

    except Exception:
        logger.exception("Unhandled error in question handler")
        return _response(500, {"error": "internal error"})
