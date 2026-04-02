import os

import boto3

from src.utils.logger import get_logger

logger = get_logger(__name__)

SUPPORTED_FORMATS = {"mp3", "mp4", "wav", "flac", "ogg", "amr", "webm"}


class TranscribeService:
    def __init__(self, transcribe_client=None, s3_client=None):
        self.transcribe_client = transcribe_client or boto3.client("transcribe")
        self.s3_client = s3_client or boto3.client("s3")

    def get_upload_metadata(self, bucket, key):
        response = self.s3_client.head_object(Bucket=bucket, Key=key)
        metadata = response.get("Metadata", {})
        return {
            "speaker": metadata.get("speaker"),
            "title": metadata.get("title"),
        }

    @staticmethod
    def derive_video_id(s3_key):
        filename = s3_key.replace("uploads/", "", 1)
        video_id, _ = os.path.splitext(filename)
        return video_id

    @staticmethod
    def detect_media_format(s3_key):
        _, ext = os.path.splitext(s3_key)
        media_format = ext.lstrip(".")
        if media_format not in SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported media format: {media_format}. "
                f"Supported: {', '.join(sorted(SUPPORTED_FORMATS))}"
            )
        return media_format

    def start_job(self, bucket, key, video_id):
        media_format = self.detect_media_format(key)
        job_name = f"production-rag-{video_id}"
        transcript_key = f"transcripts/{video_id}/raw.json"

        logger.info(
            "Starting transcription job %s for s3://%s/%s",
            job_name, bucket, key,
        )

        self.transcribe_client.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={"MediaFileUri": f"s3://{bucket}/{key}"},
            MediaFormat=media_format,
            LanguageCode="en-US",
            OutputBucketName=bucket,
            OutputKey=transcript_key,
        )

        return {
            "transcription_job_name": job_name,
            "transcript_s3_key": transcript_key,
            "status": "IN_PROGRESS",
        }

    def check_job(self, job_name):
        logger.info("Checking transcription job %s", job_name)

        response = self.transcribe_client.get_transcription_job(
            TranscriptionJobName=job_name
        )
        status = response["TranscriptionJob"]["TranscriptionJobStatus"]

        return {"status": status}


service = TranscribeService()
