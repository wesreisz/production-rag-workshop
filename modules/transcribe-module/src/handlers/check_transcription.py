import json

from src.services.transcribe_service import TranscribeService
from src.utils.logger import get_logger

logger = get_logger(__name__)

service = TranscribeService()


def handler(event: dict, context) -> dict:
    request_id = context.aws_request_id if context else "local"

    try:
        detail = event["detail"]
        job_name = detail["transcription_job_name"]

        result = service.check_job(job_name)

        return {
            "statusCode": 200,
            "detail": {
                **detail,
                "status": result["status"],
            },
        }
    except ValueError as e:
        logger.warning("bad request: %s", e, extra={"request_id": request_id})
        return {"statusCode": 400, "body": json.dumps({"error": str(e)})}
    except Exception:
        logger.exception("unhandled failure", extra={"request_id": request_id})
        return {"statusCode": 500, "body": json.dumps({"error": "internal error"})}
