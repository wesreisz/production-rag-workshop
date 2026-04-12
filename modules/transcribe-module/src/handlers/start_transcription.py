from src.services.transcribe_service import service
from src.utils.logger import get_logger

logger = get_logger(__name__)


def handler(event, context):
    request_id = getattr(context, "aws_request_id", "local")
    bucket = event["detail"]["bucket"]["name"]
    key = event["detail"]["object"]["key"]

    logger.info(
        "Starting transcription for s3://%s/%s",
        bucket, key,
        extra={"request_id": request_id},
    )

    video_id = service.derive_video_id(key)
    metadata = service.get_upload_metadata(bucket, key)
    result = service.start_job(bucket, key, video_id)

    return {
        "statusCode": 200,
        "detail": {
            "transcription_job_name": result["transcription_job_name"],
            "transcript_s3_key": result["transcript_s3_key"],
            "bucket_name": bucket,
            "source_key": key,
            "video_id": video_id,
            "speaker": metadata.get("speaker"),
            "title": metadata.get("title"),
            "status": result["status"],
        },
    }
