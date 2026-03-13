from src.services.transcribe_service import TranscribeService

service = TranscribeService()


def handler(event: dict, context) -> dict:
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
