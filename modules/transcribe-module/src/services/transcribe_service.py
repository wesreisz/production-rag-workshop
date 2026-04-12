import os

import boto3


class TranscribeService:
    def __init__(self, transcribe_client=None):
        self._client = transcribe_client or boto3.client("transcribe")

    def derive_video_id(self, s3_key):
        if "uploads/" not in s3_key:
            raise ValueError(f"Expected key with 'uploads/' prefix, got: {s3_key}")
        filename = s3_key.split("uploads/", 1)[1]
        return os.path.splitext(filename)[0]

    def detect_media_format(self, s3_key):
        return os.path.splitext(s3_key)[1].lstrip(".").lower()

    def start_job(self, bucket, key, video_id):
        media_format = self.detect_media_format(key)
        job_name = f"production-rag-{video_id}"
        transcript_key = f"transcripts/{video_id}/raw.json"

        self._client.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={"MediaFileUri": f"s3://{bucket}/{key}"},
            MediaFormat=media_format,
            LanguageCode="en-US",
            OutputBucketName=bucket,
            OutputKey=transcript_key,
        )

        return {
            "job_name": job_name,
            "transcript_key": transcript_key,
            "status": "IN_PROGRESS",
        }

    def check_job(self, job_name):
        response = self._client.get_transcription_job(
            TranscriptionJobName=job_name
        )
        status = response["TranscriptionJob"]["TranscriptionJobStatus"]
        return {"status": status}
