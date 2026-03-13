from src.services.transcribe_service import TranscribeService

service = TranscribeService()


def handler(event: dict, context) -> dict:
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
