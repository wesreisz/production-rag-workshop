import pytest

from src.services.transcribe_service import TranscribeService


class TestDeriveVideoId:
    def test_derive_video_id(self):
        # Arrange
        service = TranscribeService.__new__(TranscribeService)
        s3_key = "uploads/hello-my_name_is_wes.mp3"

        # Act
        result = service.derive_video_id(s3_key)

        # Assert
        assert result == "hello-my_name_is_wes"

    def test_derive_video_id_mp4(self):
        # Arrange
        service = TranscribeService.__new__(TranscribeService)
        s3_key = "uploads/sample.mp4"

        # Act
        result = service.derive_video_id(s3_key)

        # Assert
        assert result == "sample"

    def test_derive_video_id_rejects_missing_prefix(self):
        # Arrange
        service = TranscribeService.__new__(TranscribeService)
        s3_key = "other/sample.mp4"

        # Act & Assert
        with pytest.raises(ValueError, match="uploads/"):
            service.derive_video_id(s3_key)


class TestDetectMediaFormat:
    def test_detect_media_format_mp3(self):
        # Arrange
        service = TranscribeService.__new__(TranscribeService)
        s3_key = "uploads/sample.mp3"

        # Act
        result = service.detect_media_format(s3_key)

        # Assert
        assert result == "mp3"

    def test_detect_media_format_mp4(self):
        # Arrange
        service = TranscribeService.__new__(TranscribeService)
        s3_key = "uploads/sample.mp4"

        # Act
        result = service.detect_media_format(s3_key)

        # Assert
        assert result == "mp4"


class TestGetObjectMetadata:
    def test_get_object_metadata_returns_speaker_and_title(self, mock_aws_services):
        # Arrange
        mock_aws_services["s3"].create_bucket(Bucket="test-bucket")
        mock_aws_services["s3"].put_object(
            Bucket="test-bucket",
            Key="uploads/my-video.mp3",
            Body=b"fake",
            Metadata={"speaker": "Jane Doe", "title": "Building RAG Systems"},
        )
        service = TranscribeService(
            transcribe_client=mock_aws_services["transcribe"],
            s3_client=mock_aws_services["s3"],
        )

        # Act
        result = service.get_object_metadata("test-bucket", "uploads/my-video.mp3")

        # Assert
        assert result["speaker"] == "Jane Doe"
        assert result["title"] == "Building RAG Systems"

    def test_get_object_metadata_returns_none_when_missing(self, mock_aws_services):
        # Arrange
        mock_aws_services["s3"].create_bucket(Bucket="test-bucket")
        mock_aws_services["s3"].put_object(
            Bucket="test-bucket",
            Key="uploads/my-video.mp3",
            Body=b"fake",
        )
        service = TranscribeService(
            transcribe_client=mock_aws_services["transcribe"],
            s3_client=mock_aws_services["s3"],
        )

        # Act
        result = service.get_object_metadata("test-bucket", "uploads/my-video.mp3")

        # Assert
        assert result["speaker"] is None
        assert result["title"] is None


class TestStartJob:
    def test_start_job(self, mock_aws_services):
        # Arrange
        mock_aws_services["s3"].create_bucket(Bucket="test-bucket")
        service = TranscribeService(transcribe_client=mock_aws_services["transcribe"])

        # Act
        result = service.start_job("test-bucket", "uploads/hello-my_name_is_wes.mp3", "hello-my_name_is_wes")

        # Assert
        assert result["job_name"] == "production-rag-hello-my_name_is_wes"
        assert result["transcript_key"] == "transcripts/hello-my_name_is_wes/raw.json"
        assert result["status"] == "IN_PROGRESS"


class TestCheckJob:
    def test_check_job_in_progress(self, mock_aws_services):
        # Arrange
        mock_aws_services["s3"].create_bucket(Bucket="test-bucket")
        service = TranscribeService(transcribe_client=mock_aws_services["transcribe"])
        service.start_job("test-bucket", "uploads/hello-my_name_is_wes.mp3", "hello-my_name_is_wes")

        # Act
        result = service.check_job("production-rag-hello-my_name_is_wes")

        # Assert (moto returns QUEUED for a freshly started job)
        assert result["status"] == "QUEUED"
