import json

from src.services.embedding_service import EmbeddingService
from src.utils.logger import get_logger

logger = get_logger(__name__)
service = EmbeddingService()


def handler(event, context):
    request_id = getattr(context, "aws_request_id", "unknown") if context else "unknown"

    for record in event["Records"]:
        body = json.loads(record["body"])
        bucket = body["bucket"]
        chunk_s3_key = body["chunk_s3_key"]
        video_id = body["video_id"]

        chunk = service.read_chunk(bucket, chunk_s3_key)
        embedding = service.generate_embedding(chunk["text"])
        service.store_embedding(chunk, embedding)

        logger.info(
            "Embedded chunk %s for video %s",
            chunk["chunk_id"],
            video_id,
            extra={"request_id": request_id},
        )
