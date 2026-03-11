import json

from src.services.transcribe_service import TranscribeService
from src.utils.logger import get_logger

logger = get_logger(__name__)

service = TranscribeService()


def handler(event: dict, context) -> dict:
    request_id = context.aws_request_id if context else "local"

    try:
        bucket = event["detail"]["bucket"]["name"]
        key = event["detail"]["object"]["key"]

        metadata = service.get_object_metadata(bucket, key)
        video_id = service.derive_video_id(key)
        result = service.start_job(bucket, key, video_id)

        return {
            "statusCode": 200,
            "detail": {
                "transcription_job_name": result["transcription_job_name"],
                "transcript_s3_key": result["transcript_s3_key"],
                "bucket_name": bucket,
                "source_key": key,
                "video_id": video_id,
                "speaker": metadata["speaker"],
                "title": metadata["title"],
                "status": result["status"],
            },
        }
    except ValueError as e:
        logger.warning("bad request: %s", e, extra={"request_id": request_id})
        return {"statusCode": 400, "body": json.dumps({"error": str(e)})}
    except Exception:
        logger.exception("unhandled failure", extra={"request_id": request_id})
        return {"statusCode": 500, "body": json.dumps({"error": "internal error"})}
