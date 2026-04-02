from unittest.mock import MagicMock, patch

import pytest

from src.services.transcribe_service import TranscribeService


class TestDeriveVideoId:
    def test_mp3_file(self):
        # Arrange
        s3_key = "uploads/hello-my_name_is_wes.mp3"

        # Act
        result = TranscribeService.derive_video_id(s3_key)

        # Assert
        assert result == "hello-my_name_is_wes"

    def test_mp4_file(self):
        # Arrange
        s3_key = "uploads/sample.mp4"

        # Act
        result = TranscribeService.derive_video_id(s3_key)

        # Assert
        assert result == "sample"

    def test_wav_file(self):
        # Arrange
        s3_key = "uploads/my-talk.wav"

        # Act
        result = TranscribeService.derive_video_id(s3_key)

        # Assert
        assert result == "my-talk"


class TestDetectMediaFormat:
    def test_mp3(self):
        # Arrange
        s3_key = "uploads/file.mp3"

        # Act
        result = TranscribeService.detect_media_format(s3_key)

        # Assert
        assert result == "mp3"

    def test_mp4(self):
        # Arrange
        s3_key = "uploads/file.mp4"

        # Act
        result = TranscribeService.detect_media_format(s3_key)

        # Assert
        assert result == "mp4"

    def test_wav(self):
        # Arrange
        s3_key = "uploads/file.wav"

        # Act
        result = TranscribeService.detect_media_format(s3_key)

        # Assert
        assert result == "wav"

    def test_flac(self):
        # Arrange
        s3_key = "uploads/file.flac"

        # Act
        result = TranscribeService.detect_media_format(s3_key)

        # Assert
        assert result == "flac"

    def test_unsupported_format_raises(self):
        # Arrange
        s3_key = "uploads/file.txt"

        # Act & Assert
        with pytest.raises(ValueError, match="Unsupported media format"):
            TranscribeService.detect_media_format(s3_key)


class TestGetUploadMetadata:
    def test_returns_speaker_and_title(self, mock_aws_services):
        # Arrange
        s3_client = mock_aws_services["s3"]
        s3_client.create_bucket(Bucket="test-bucket")
        s3_client.put_object(
            Bucket="test-bucket",
            Key="uploads/sample.mp3",
            Body=b"fake audio",
            Metadata={"speaker": "Jane", "title": "Talk"},
        )
        svc = TranscribeService(s3_client=s3_client)

        # Act
        result = svc.get_upload_metadata("test-bucket", "uploads/sample.mp3")

        # Assert
        assert result["speaker"] == "Jane"
        assert result["title"] == "Talk"

    def test_returns_none_when_no_metadata(self, mock_aws_services):
        # Arrange
        s3_client = mock_aws_services["s3"]
        s3_client.create_bucket(Bucket="test-bucket")
        s3_client.put_object(
            Bucket="test-bucket",
            Key="uploads/sample.mp3",
            Body=b"fake audio",
        )
        svc = TranscribeService(s3_client=s3_client)

        # Act
        result = svc.get_upload_metadata("test-bucket", "uploads/sample.mp3")

        # Assert
        assert result["speaker"] is None
        assert result["title"] is None


class TestStartJob:
    def test_starts_transcription_job(self, mock_aws_services):
        # Arrange
        s3_client = mock_aws_services["s3"]
        s3_client.create_bucket(Bucket="test-bucket")
        s3_client.put_object(
            Bucket="test-bucket",
            Key="uploads/sample.mp3",
            Body=b"fake audio",
        )
        transcribe_client = mock_aws_services["transcribe"]
        svc = TranscribeService(transcribe_client=transcribe_client)

        # Act
        result = svc.start_job("test-bucket", "uploads/sample.mp3", "sample")

        # Assert
        assert result["transcription_job_name"] == "production-rag-sample"
        assert result["transcript_s3_key"] == "transcripts/sample/raw.json"
        assert result["status"] == "IN_PROGRESS"

    def test_unsupported_format_raises(self, mock_aws_services):
        # Arrange
        transcribe_client = mock_aws_services["transcribe"]
        svc = TranscribeService(transcribe_client=transcribe_client)

        # Act & Assert
        with pytest.raises(ValueError, match="Unsupported media format"):
            svc.start_job("test-bucket", "uploads/file.txt", "file")


class TestCheckJob:
    def test_returns_completed_status(self):
        # Arrange
        mock_client = MagicMock()
        mock_client.get_transcription_job.return_value = {
            "TranscriptionJob": {
                "TranscriptionJobStatus": "COMPLETED",
            }
        }
        svc = TranscribeService(transcribe_client=mock_client)

        # Act
        result = svc.check_job("production-rag-sample")

        # Assert
        assert result["status"] == "COMPLETED"
        mock_client.get_transcription_job.assert_called_once_with(
            TranscriptionJobName="production-rag-sample"
        )

    def test_returns_in_progress_status(self):
        # Arrange
        mock_client = MagicMock()
        mock_client.get_transcription_job.return_value = {
            "TranscriptionJob": {
                "TranscriptionJobStatus": "IN_PROGRESS",
            }
        }
        svc = TranscribeService(transcribe_client=mock_client)

        # Act
        result = svc.check_job("production-rag-sample")

        # Assert
        assert result["status"] == "IN_PROGRESS"

    def test_returns_failed_status(self):
        # Arrange
        mock_client = MagicMock()
        mock_client.get_transcription_job.return_value = {
            "TranscriptionJob": {
                "TranscriptionJobStatus": "FAILED",
            }
        }
        svc = TranscribeService(transcribe_client=mock_client)

        # Act
        result = svc.check_job("production-rag-sample")

        # Assert
        assert result["status"] == "FAILED"
