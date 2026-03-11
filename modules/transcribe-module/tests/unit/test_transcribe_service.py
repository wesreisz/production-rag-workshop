from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from src.services.transcribe_service import TranscribeService


class TestDeriveVideoId:
    def test_strips_prefix_and_extension(self):
        # Arrange
        service = TranscribeService()

        # Act
        result = service.derive_video_id("uploads/sample.mp4")

        # Assert
        assert result == "sample"

    def test_handles_mp3(self):
        # Arrange
        service = TranscribeService()

        # Act
        result = service.derive_video_id("uploads/hello-my_name_is_wes.mp3")

        # Assert
        assert result == "hello-my_name_is_wes"

    def test_handles_hyphenated_name(self):
        # Arrange
        service = TranscribeService()

        # Act
        result = service.derive_video_id("uploads/my-talk.wav")

        # Assert
        assert result == "my-talk"


class TestDetectMediaFormat:
    def test_detects_mp4(self):
        # Arrange
        service = TranscribeService()

        # Act
        result = service.detect_media_format("uploads/sample.mp4")

        # Assert
        assert result == "mp4"

    def test_detects_mp3(self):
        # Arrange
        service = TranscribeService()

        # Act
        result = service.detect_media_format("uploads/sample.mp3")

        # Assert
        assert result == "mp3"

    def test_raises_for_unsupported(self):
        # Arrange
        service = TranscribeService()

        # Act / Assert
        with pytest.raises(ValueError, match="Unsupported media format"):
            service.detect_media_format("uploads/sample.txt")


class TestGetObjectMetadata:
    @mock_aws
    def test_returns_speaker_and_title(self):
        # Arrange
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")
        s3.put_object(
            Bucket="test-bucket",
            Key="uploads/sample.mp4",
            Body=b"fake video",
            Metadata={"speaker": "Jane Doe", "title": "Building RAG Systems"},
        )
        service = TranscribeService()

        # Act
        result = service.get_object_metadata("test-bucket", "uploads/sample.mp4")

        # Assert
        assert result["speaker"] == "Jane Doe"
        assert result["title"] == "Building RAG Systems"

    @mock_aws
    def test_returns_none_when_metadata_absent(self):
        # Arrange
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")
        s3.put_object(
            Bucket="test-bucket",
            Key="uploads/sample.mp4",
            Body=b"fake video",
        )
        service = TranscribeService()

        # Act
        result = service.get_object_metadata("test-bucket", "uploads/sample.mp4")

        # Assert
        assert result["speaker"] is None
        assert result["title"] is None


class TestStartJob:
    @mock_aws
    @patch("src.services.transcribe_service.time.time", return_value=1700000000)
    def test_starts_transcription_job(self, _mock_time):
        # Arrange
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")
        s3.put_object(Bucket="test-bucket", Key="uploads/sample.mp4", Body=b"fake video")

        service = TranscribeService()

        # Act
        result = service.start_job("test-bucket", "uploads/sample.mp4", "sample")

        # Assert
        assert result["transcription_job_name"] == "production-rag-sample-1700000000"
        assert result["transcript_s3_key"] == "transcripts/sample/raw.json"
        assert result["status"] == "IN_PROGRESS"


class TestCheckJob:
    @mock_aws
    def test_returns_job_status(self):
        # Arrange
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")
        s3.put_object(Bucket="test-bucket", Key="uploads/sample.mp4", Body=b"fake video")

        transcribe = boto3.client("transcribe", region_name="us-east-1")
        transcribe.start_transcription_job(
            TranscriptionJobName="production-rag-sample",
            Media={"MediaFileUri": "s3://test-bucket/uploads/sample.mp4"},
            MediaFormat="mp4",
            LanguageCode="en-US",
            OutputBucketName="test-bucket",
            OutputKey="transcripts/sample/raw.json",
        )

        service = TranscribeService()

        # Act
        result = service.check_job("production-rag-sample")

        # Assert
        assert result["status"] in ("QUEUED", "IN_PROGRESS", "COMPLETED")
