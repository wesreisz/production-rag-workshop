import json

from src.services.chunking_service import ChunkingService
from src.utils.logger import get_logger

logger = get_logger(__name__)

service = ChunkingService()


def handler(event: dict, context) -> dict:
    request_id = context.aws_request_id if context else "local"

    try:
        detail = event["detail"]
        bucket_name = detail["bucket_name"]
        transcript_s3_key = detail["transcript_s3_key"]
        video_id = detail["video_id"]
        source_key = detail["source_key"]

        transcript = service.read_transcript(bucket_name, transcript_s3_key)
        timed_words = service.parse_timed_words(transcript)
        chunks = service.chunk(timed_words, video_id, source_key)
        chunk_keys = service.store_chunks(bucket_name, video_id, chunks)

        return {
            "statusCode": 200,
            "detail": {
                "chunk_count": len(chunks),
                "chunks_s3_prefix": f"chunks/{video_id}/",
                "chunk_keys": chunk_keys,
                "video_id": video_id,
                "bucket_name": bucket_name,
            },
        }
    except ValueError as e:
        logger.warning("bad request: %s", e, extra={"request_id": request_id})
        return {"statusCode": 400, "body": json.dumps({"error": str(e)})}
    except Exception:
        logger.exception("unhandled failure", extra={"request_id": request_id})
        return {"statusCode": 500, "body": json.dumps({"error": "internal error"})}
