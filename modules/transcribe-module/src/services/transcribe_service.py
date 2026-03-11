import time
from pathlib import PurePosixPath

import boto3
from botocore.config import Config

from src.utils.logger import get_logger

logger = get_logger(__name__)

RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})
SUPPORTED_FORMATS = {"mp3", "mp4", "wav", "flac", "ogg", "amr", "webm"}


class TranscribeService:
    def __init__(self) -> None:
        self._client = boto3.client("transcribe", config=RETRY_CONFIG)
        self._s3 = boto3.client("s3")

    def get_object_metadata(self, bucket: str, key: str) -> dict:
        response = self._s3.head_object(Bucket=bucket, Key=key)
        metadata = response.get("Metadata", {})
        return {
            "speaker": metadata.get("speaker"),
            "title": metadata.get("title"),
        }

    def derive_video_id(self, s3_key: str) -> str:
        filename = s3_key.removeprefix("uploads/")
        return PurePosixPath(filename).stem

    def detect_media_format(self, s3_key: str) -> str:
        extension = PurePosixPath(s3_key).suffix.lstrip(".")
        if extension not in SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported media format: {extension}")
        return extension

    def start_job(self, bucket: str, key: str, video_id: str) -> dict[str, str]:
        media_format = self.detect_media_format(key)
        job_name = f"production-rag-{video_id}-{int(time.time())}"
        transcript_key = f"transcripts/{video_id}/raw.json"

        self._client.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={"MediaFileUri": f"s3://{bucket}/{key}"},
            MediaFormat=media_format,
            LanguageCode="en-US",
            OutputBucketName=bucket,
            OutputKey=transcript_key,
        )

        logger.info(
            "started transcription job %s for %s/%s",
            job_name,
            bucket,
            key,
        )

        return {
            "transcription_job_name": job_name,
            "transcript_s3_key": transcript_key,
            "status": "IN_PROGRESS",
        }

    def check_job(self, job_name: str) -> dict[str, str]:
        response = self._client.get_transcription_job(
            TranscriptionJobName=job_name
        )
        status = response["TranscriptionJob"]["TranscriptionJobStatus"]

        logger.info("transcription job %s status: %s", job_name, status)

        return {"status": status}
