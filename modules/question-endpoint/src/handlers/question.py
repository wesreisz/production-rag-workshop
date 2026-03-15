import json

from src.services.retrieval_service import RetrievalService
from src.utils.logger import get_logger

logger = get_logger(__name__)
service = RetrievalService()


def handler(event, context):
    try:
        resource = event.get("resource", "")

        if resource == "/health":
            return _response(200, {"status": "healthy"})

        if resource == "/videos":
            videos = service.list_videos()
            return _response(200, {"videos": videos})

        if resource == "/ask":
            return _handle_ask(event)

        if resource == "/videos/{video_id}/ask":
            return _handle_video_ask(event)

        return _response(404, {"error": "not found"})
    except Exception:
        logger.exception("unhandled error")
        return _response(500, {"error": "internal error"})


def _handle_ask(event):
    body = json.loads(event.get("body") or "{}")

    question = body.get("question", "").strip() if isinstance(body.get("question"), str) else ""
    if not question:
        return _response(400, {"error": "question is required"})

    top_k = body.get("top_k", 5)
    if not isinstance(top_k, int) or top_k < 1 or top_k > 100:
        return _response(400, {"error": "top_k must be between 1 and 100"})

    similarity_threshold = body.get("similarity_threshold", 0.0)
    if not isinstance(similarity_threshold, (int, float)) or similarity_threshold < 0.0 or similarity_threshold > 1.0:
        return _response(400, {"error": "similarity_threshold must be between 0.0 and 1.0"})

    speaker = None
    filters = body.get("filters")
    if isinstance(filters, dict):
        speaker = filters.get("speaker")

    embedding = service.generate_embedding(question)
    results = service.search_similar(
        embedding,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
        speaker=speaker,
    )

    return _response(200, {"question": question, "results": results})


def _handle_video_ask(event):
    video_id = event.get("pathParameters", {}).get("video_id", "")
    body = json.loads(event.get("body") or "{}")

    question = body.get("question", "").strip() if isinstance(body.get("question"), str) else ""
    if not question:
        return _response(400, {"error": "question is required"})

    top_k = body.get("top_k", 5)
    if not isinstance(top_k, int) or top_k < 1 or top_k > 100:
        return _response(400, {"error": "top_k must be between 1 and 100"})

    similarity_threshold = body.get("similarity_threshold", 0.0)
    if not isinstance(similarity_threshold, (int, float)) or similarity_threshold < 0.0 or similarity_threshold > 1.0:
        return _response(400, {"error": "similarity_threshold must be between 0.0 and 1.0"})

    embedding = service.generate_embedding(question)
    results = service.search_similar(
        embedding,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
        video_id=video_id,
    )

    return _response(200, {"video_id": video_id, "question": question, "results": results})


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }
