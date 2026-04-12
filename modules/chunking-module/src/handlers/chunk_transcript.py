import os

from src.services.chunking_service import ChunkingService
from src.utils.logger import get_logger

logger = get_logger(__name__)
service = ChunkingService()


def handler(event, context):
    request_id = getattr(context, "aws_request_id", "unknown") if context else "unknown"
    logger.info("Starting chunking", extra={"request_id": request_id})

    detail = event["detail"]
    bucket_name = detail["bucket_name"]
    transcript_s3_key = detail["transcript_s3_key"]
    video_id = detail["video_id"]
    source_key = detail["source_key"]
    speaker = detail.get("speaker")
    title = detail.get("title")
    queue_url = os.environ["EMBEDDING_QUEUE_URL"]

    transcript = service.read_transcript(bucket_name, transcript_s3_key)
    timed_words = service.parse_timed_words(transcript)
    chunks = service.chunk(timed_words, video_id, source_key, speaker, title)
    chunk_keys = service.store_chunks(bucket_name, video_id, chunks)
    messages_published = service.publish_chunks(
        queue_url, chunk_keys, bucket_name, video_id, speaker, title
    )

    return {
        "statusCode": 200,
        "detail": {
            "chunk_count": len(chunks),
            "chunks_s3_prefix": f"chunks/{video_id}/",
            "chunk_keys": chunk_keys,
            "messages_published": messages_published,
            "video_id": video_id,
            "bucket_name": bucket_name,
        },
    }
