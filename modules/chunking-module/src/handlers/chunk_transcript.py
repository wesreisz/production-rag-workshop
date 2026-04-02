import os

from src.services.chunking_service import service
from src.utils.logger import get_logger

logger = get_logger(__name__)


def handler(event, context):
    request_id = getattr(context, "aws_request_id", "local")

    detail = event["detail"]
    bucket_name = detail["bucket_name"]
    transcript_s3_key = detail["transcript_s3_key"]
    video_id = detail["video_id"]
    source_key = detail["source_key"]
    speaker = detail.get("speaker")
    title = detail.get("title")
    queue_url = os.environ["EMBEDDING_QUEUE_URL"]

    logger.info(
        "Chunking transcript for video %s",
        video_id,
        extra={"request_id": request_id},
    )

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
