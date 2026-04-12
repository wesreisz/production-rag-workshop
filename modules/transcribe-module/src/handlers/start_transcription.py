from src.services.transcribe_service import TranscribeService
from src.utils.logger import get_logger

logger = get_logger(__name__)
service = TranscribeService()


def handler(event, context):
    request_id = getattr(context, "aws_request_id", "unknown") if context else "unknown"
    try:
        bucket_name = event["detail"]["bucket"]["name"]
        object_key = event["detail"]["object"]["key"]

        logger.info("Starting transcription", extra={"request_id": request_id})

        video_id = service.derive_video_id(object_key)
        metadata = service.get_object_metadata(bucket_name, object_key)
        result = service.start_job(bucket_name, object_key, video_id)

        return {
            "statusCode": 200,
            "detail": {
                "transcription_job_name": result["job_name"],
                "transcript_s3_key": result["transcript_key"],
                "bucket_name": bucket_name,
                "source_key": object_key,
                "video_id": video_id,
                "speaker": metadata["speaker"],
                "title": metadata["title"],
                "status": result["status"],
            },
        }
    except ValueError as e:
        logger.error(str(e), extra={"request_id": request_id})
        return {"statusCode": 400, "detail": {"error": str(e)}}
