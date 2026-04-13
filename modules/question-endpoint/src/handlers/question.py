import json

from src.services.retrieval_service import RetrievalService
from src.utils.logger import get_logger

logger = get_logger(__name__)
service = RetrievalService()


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def _validate_ask_body(body):
    question = body.get("question", "")
    if not question or not isinstance(question, str) or question.strip() == "":
        return None, None, None, None, _response(400, {"error": "question is required"})

    top_k = body.get("top_k", 5)
    if not isinstance(top_k, int) or top_k < 1 or top_k > 100:
        return None, None, None, None, _response(400, {"error": "top_k must be between 1 and 100"})

    similarity_threshold = body.get("similarity_threshold", 0.0)
    if not isinstance(similarity_threshold, (int, float)) or similarity_threshold < 0.0 or similarity_threshold > 1.0:
        return None, None, None, None, _response(400, {"error": "similarity_threshold must be between 0.0 and 1.0"})

    speaker = body.get("filters", {}).get("speaker")

    return question, top_k, float(similarity_threshold), speaker, None


def handler(event, context):
    request_id = getattr(context, "aws_request_id", "unknown") if context else "unknown"
    resource = event.get("resource", "")
    http_method = event.get("httpMethod", "")

    if http_method == "GET" and resource == "/health":
        return _response(200, {"status": "healthy"})

    if http_method == "GET" and resource == "/videos":
        try:
            results = service.list_videos()
            return _response(200, {"videos": results})
        except Exception:
            logger.exception("Error listing videos", extra={"request_id": request_id})
            return _response(500, {"error": "internal error"})

    if http_method == "POST" and resource == "/ask":
        try:
            try:
                body = json.loads(event.get("body", "{}"))
            except (json.JSONDecodeError, TypeError):
                return _response(400, {"error": "question is required"})

            question, top_k, similarity_threshold, speaker, error_response = _validate_ask_body(body)
            if error_response:
                return error_response

            embedding = service.generate_embedding(question)
            results = service.search_similar(embedding, top_k, similarity_threshold, speaker=speaker)

            logger.info(
                "Search completed for question: %s, results: %d",
                question, len(results),
                extra={"request_id": request_id},
            )

            return _response(200, {"question": question, "results": results})
        except Exception:
            logger.exception("Error processing /ask", extra={"request_id": request_id})
            return _response(500, {"error": "internal error"})

    if http_method == "POST" and resource == "/videos/{video_id}/ask":
        try:
            video_id = event["pathParameters"]["video_id"]

            try:
                body = json.loads(event.get("body", "{}"))
            except (json.JSONDecodeError, TypeError):
                return _response(400, {"error": "question is required"})

            question, top_k, similarity_threshold, _, error_response = _validate_ask_body(body)
            if error_response:
                return error_response

            embedding = service.generate_embedding(question)
            results = service.search_similar(embedding, top_k, similarity_threshold, video_id=video_id)

            logger.info(
                "Search completed for video %s, question: %s, results: %d",
                video_id, question, len(results),
                extra={"request_id": request_id},
            )

            return _response(200, {"video_id": video_id, "question": question, "results": results})
        except Exception:
            logger.exception("Error processing /videos/{video_id}/ask", extra={"request_id": request_id})
            return _response(500, {"error": "internal error"})

    return _response(404, {"error": "not found"})
