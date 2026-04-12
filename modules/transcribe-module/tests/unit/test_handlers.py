from unittest.mock import MagicMock, patch

import pytest

with patch("boto3.client"):
    import src.handlers.check_transcription as check_module
    import src.handlers.start_transcription as start_module


class TestStartTranscriptionHandler:
    def _make_event(self, bucket="test-bucket", key="uploads/my-video.mp4"):
        return {
            "detail": {
                "bucket": {"name": bucket},
                "object": {"key": key},
            }
        }

    def test_returns_200_with_correct_detail(self):
        # Arrange
        mock_service = MagicMock()
        mock_service.derive_video_id.return_value = "my-video"
        mock_service.start_job.return_value = {
            "job_name": "production-rag-my-video",
            "transcript_key": "transcripts/my-video/raw.json",
            "status": "IN_PROGRESS",
        }
        event = self._make_event()
        context = MagicMock(aws_request_id="test-123")

        # Act
        with patch.object(start_module, "service", mock_service):
            result = start_module.handler(event, context)

        # Assert
        assert result["statusCode"] == 200
        detail = result["detail"]
        assert detail["transcription_job_name"] == "production-rag-my-video"
        assert detail["transcript_s3_key"] == "transcripts/my-video/raw.json"
        assert detail["bucket_name"] == "test-bucket"
        assert detail["source_key"] == "uploads/my-video.mp4"
        assert detail["video_id"] == "my-video"
        assert detail["status"] == "IN_PROGRESS"

    def test_returns_400_on_value_error(self):
        # Arrange
        mock_service = MagicMock()
        mock_service.derive_video_id.side_effect = ValueError("bad key")
        event = self._make_event(key="bad-key")
        context = MagicMock(aws_request_id="test-123")

        # Act
        with patch.object(start_module, "service", mock_service):
            result = start_module.handler(event, context)

        # Assert
        assert result["statusCode"] == 400
        assert "bad key" in result["detail"]["error"]

    def test_propagates_transient_errors(self):
        # Arrange
        mock_service = MagicMock()
        mock_service.derive_video_id.return_value = "my-video"
        mock_service.start_job.side_effect = RuntimeError("service unavailable")
        event = self._make_event()
        context = MagicMock(aws_request_id="test-123")

        # Act & Assert
        with patch.object(start_module, "service", mock_service):
            with pytest.raises(RuntimeError, match="service unavailable"):
                start_module.handler(event, context)


class TestCheckTranscriptionHandler:
    def _make_event(self):
        return {
            "detail": {
                "transcription_job_name": "production-rag-my-video",
                "transcript_s3_key": "transcripts/my-video/raw.json",
                "bucket_name": "test-bucket",
                "source_key": "uploads/my-video.mp4",
                "video_id": "my-video",
            }
        }

    def test_returns_200_with_updated_status(self):
        # Arrange
        mock_service = MagicMock()
        mock_service.check_job.return_value = {"status": "COMPLETED"}
        event = self._make_event()
        context = MagicMock(aws_request_id="test-123")

        # Act
        with patch.object(check_module, "service", mock_service):
            result = check_module.handler(event, context)

        # Assert
        assert result["statusCode"] == 200
        detail = result["detail"]
        assert detail["status"] == "COMPLETED"
        assert detail["transcription_job_name"] == "production-rag-my-video"
        assert detail["transcript_s3_key"] == "transcripts/my-video/raw.json"
        assert detail["bucket_name"] == "test-bucket"
        assert detail["source_key"] == "uploads/my-video.mp4"
        assert detail["video_id"] == "my-video"

    def test_returns_400_on_value_error(self):
        # Arrange
        mock_service = MagicMock()
        mock_service.check_job.side_effect = ValueError("invalid job")
        event = self._make_event()
        context = MagicMock(aws_request_id="test-123")

        # Act
        with patch.object(check_module, "service", mock_service):
            result = check_module.handler(event, context)

        # Assert
        assert result["statusCode"] == 400
        assert "invalid job" in result["detail"]["error"]

    def test_propagates_transient_errors(self):
        # Arrange
        mock_service = MagicMock()
        mock_service.check_job.side_effect = RuntimeError("throttled")
        event = self._make_event()
        context = MagicMock(aws_request_id="test-123")

        # Act & Assert
        with patch.object(check_module, "service", mock_service):
            with pytest.raises(RuntimeError, match="throttled"):
                check_module.handler(event, context)

    def test_propagates_key_error_on_malformed_event(self):
        # Arrange
        mock_service = MagicMock()
        event = {"detail": {}}
        context = MagicMock(aws_request_id="test-123")

        # Act & Assert
        with patch.object(check_module, "service", mock_service):
            with pytest.raises(KeyError):
                check_module.handler(event, context)
