from src.services.transcribe_service import service
from src.utils.logger import get_logger

logger = get_logger(__name__)


def handler(event, context):
    request_id = getattr(context, "aws_request_id", "local")
    try:
        detail = event["detail"]
        job_name = detail["transcription_job_name"]

        logger.info(
            "Checking transcription job %s",
            job_name,
            extra={"request_id": request_id},
        )

        result = service.check_job(job_name)

        return {
            "statusCode": 200,
            "detail": {
                "transcription_job_name": detail["transcription_job_name"],
                "transcript_s3_key": detail["transcript_s3_key"],
                "bucket_name": detail["bucket_name"],
                "source_key": detail["source_key"],
                "video_id": detail["video_id"],
                "status": result["status"],
            },
        }

    except ValueError as e:
        logger.error("Validation error: %s", e, extra={"request_id": request_id})
        return {"statusCode": 400, "detail": {"error": str(e)}}

    except Exception as e:
        logger.error("Unexpected error: %s", e, extra={"request_id": request_id})
        return {"statusCode": 500, "detail": {"error": "internal error"}}
