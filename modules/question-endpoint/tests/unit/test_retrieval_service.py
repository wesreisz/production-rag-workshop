import io
import json
import os
from unittest.mock import MagicMock, patch

from botocore.response import StreamingBody

os.environ.setdefault("SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123456789012:secret:test-secret")
os.environ.setdefault("DB_NAME", "ragdb")
os.environ.setdefault("EMBEDDING_DIMENSIONS", "256")

from src.services.retrieval_service import RetrievalService

with patch("boto3.client"):
    import src.handlers.question as handler_module


class TestGenerateEmbedding:
    def _make_bedrock_response(self, embedding):
        body_bytes = json.dumps({
            "embedding": embedding,
            "inputTextTokenCount": 10,
        }).encode("utf-8")
        return {
            "body": StreamingBody(io.BytesIO(body_bytes), len(body_bytes)),
        }

    def test_generate_embedding_returns_vector(self, aws_credentials):
        # Arrange
        expected_embedding = [float(i) * 0.01 for i in range(256)]
        mock_bedrock = MagicMock()
        mock_bedrock.invoke_model.return_value = self._make_bedrock_response(expected_embedding)
        service = RetrievalService(
            bedrock_client=mock_bedrock,
            secretsmanager_client=MagicMock(),
        )

        # Act
        result = service.generate_embedding("What is RAG?")

        # Assert
        assert result == expected_embedding
        assert len(result) == 256
        assert all(isinstance(v, float) for v in result)

    def test_generate_embedding_passes_correct_params(self, aws_credentials):
        # Arrange
        mock_bedrock = MagicMock()
        mock_bedrock.invoke_model.return_value = self._make_bedrock_response([0.0] * 256)
        service = RetrievalService(
            bedrock_client=mock_bedrock,
            secretsmanager_client=MagicMock(),
        )

        # Act
        service.generate_embedding("Test text")

        # Assert
        call_kwargs = mock_bedrock.invoke_model.call_args[1]
        assert call_kwargs["modelId"] == "amazon.titan-embed-text-v2:0"
        assert call_kwargs["contentType"] == "application/json"
        assert call_kwargs["accept"] == "application/json"
        body = json.loads(call_kwargs["body"])
        assert body["inputText"] == "Test text"
        assert body["dimensions"] == 256
        assert body["normalize"] is True


class TestSearchSimilar:
    def _make_service_with_mock_db(self, rows):
        service = RetrievalService.__new__(RetrievalService)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = rows
        service.get_db_connection = MagicMock(return_value=mock_conn)
        return service, mock_cursor

    def test_search_similar_returns_ranked_results(self, aws_credentials):
        # Arrange
        rows = [
            ("chunk-001", "vid-1", "Some text", "Jane", "Title", 0.0, 45.2, "uploads/vid.mp3", 0.95),
            ("chunk-002", "vid-1", "More text", "Jane", "Title", 45.2, 90.0, "uploads/vid.mp3", 0.85),
        ]
        service, _ = self._make_service_with_mock_db(rows)
        embedding = [0.01] * 256

        # Act
        results = service.search_similar(embedding, top_k=5)

        # Assert
        assert len(results) == 2
        assert results[0]["chunk_id"] == "chunk-001"
        assert results[0]["similarity"] == 0.95
        assert results[1]["chunk_id"] == "chunk-002"
        assert set(results[0].keys()) == {
            "chunk_id", "video_id", "text", "speaker", "title",
            "start_time", "end_time", "source_s3_key", "similarity",
        }

    def test_search_similar_with_speaker_filter(self, aws_credentials):
        # Arrange
        rows = [("chunk-001", "vid-1", "Text", "Jane", "Title", 0.0, 45.2, "uploads/vid.mp3", 0.9)]
        service, mock_cursor = self._make_service_with_mock_db(rows)
        embedding = [0.01] * 256

        # Act
        service.search_similar(embedding, top_k=5, speaker="Jane")

        # Assert
        sql = mock_cursor.execute.call_args[0][0]
        assert "WHERE" in sql
        assert "speaker = %s" in sql

    def test_search_similar_without_filter(self, aws_credentials):
        # Arrange
        rows = []
        service, mock_cursor = self._make_service_with_mock_db(rows)
        embedding = [0.01] * 256

        # Act
        service.search_similar(embedding, top_k=5)

        # Assert
        sql = mock_cursor.execute.call_args[0][0]
        assert "WHERE" not in sql

    def test_search_similar_filters_below_threshold(self, aws_credentials):
        # Arrange
        rows = [
            ("chunk-001", "vid-1", "High", "Jane", "Title", 0.0, 10.0, "uploads/vid.mp3", 0.9),
            ("chunk-002", "vid-1", "Low", "Jane", "Title", 10.0, 20.0, "uploads/vid.mp3", 0.4),
            ("chunk-003", "vid-1", "Mid", "Jane", "Title", 20.0, 30.0, "uploads/vid.mp3", 0.7),
        ]
        service, _ = self._make_service_with_mock_db(rows)
        embedding = [0.01] * 256

        # Act
        results = service.search_similar(embedding, top_k=5, similarity_threshold=0.5)

        # Assert
        assert len(results) == 2
        assert results[0]["similarity"] == 0.9
        assert results[1]["similarity"] == 0.7

    def test_search_similar_with_video_id_filter(self, aws_credentials):
        # Arrange
        rows = [("chunk-001", "test-vid", "Text", "Jane", "Title", 0.0, 45.2, "uploads/vid.mp3", 0.9)]
        service, mock_cursor = self._make_service_with_mock_db(rows)
        embedding = [0.01] * 256

        # Act
        service.search_similar(embedding, top_k=5, video_id="test-vid")

        # Assert
        sql = mock_cursor.execute.call_args[0][0]
        assert "WHERE" in sql
        assert "video_id = %s" in sql


class TestListVideos:
    def test_list_videos_returns_aggregated(self, aws_credentials):
        # Arrange
        rows = [
            ("vid-1", "Jane Doe", "Building RAG", 3),
            ("vid-2", "John Smith", "Intro to ML", 5),
        ]
        service = RetrievalService.__new__(RetrievalService)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = rows
        service.get_db_connection = MagicMock(return_value=mock_conn)

        # Act
        results = service.list_videos()

        # Assert
        assert len(results) == 2
        assert results[0] == {
            "video_id": "vid-1",
            "speaker": "Jane Doe",
            "title": "Building RAG",
            "chunk_count": 3,
        }
        assert results[1]["video_id"] == "vid-2"
        assert results[1]["chunk_count"] == 5


class TestHandler:
    def test_handler_post_ask_returns_results(self, sample_ask_event):
        # Arrange
        mock_service = MagicMock()
        mock_service.generate_embedding.return_value = [0.0] * 256
        mock_service.search_similar.return_value = [
            {"chunk_id": "chunk-001", "similarity": 0.9, "text": "Some text"},
        ]
        context = MagicMock(aws_request_id="test-123")

        # Act
        with patch.object(handler_module, "service", mock_service):
            result = handler_module.handler(sample_ask_event, context)

        # Assert
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["question"] == "What is RAG?"
        assert len(body["results"]) == 1
        assert body["results"][0]["chunk_id"] == "chunk-001"

    def test_handler_post_ask_missing_question(self):
        # Arrange
        event = {
            "resource": "/ask",
            "httpMethod": "POST",
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"question": ""}),
        }
        context = MagicMock(aws_request_id="test-123")

        # Act
        with patch.object(handler_module, "service", MagicMock()):
            result = handler_module.handler(event, context)

        # Assert
        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error"] == "question is required"

    def test_handler_post_video_ask_returns_results(self, sample_video_ask_event):
        # Arrange
        mock_service = MagicMock()
        mock_service.generate_embedding.return_value = [0.0] * 256
        mock_service.search_similar.return_value = [
            {"chunk_id": "chunk-001", "similarity": 0.9, "text": "Some text"},
        ]
        context = MagicMock(aws_request_id="test-123")

        # Act
        with patch.object(handler_module, "service", mock_service):
            result = handler_module.handler(sample_video_ask_event, context)

        # Assert
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["video_id"] == "hello-my_name_is_wes"
        assert body["question"] == "What is this about?"
        assert len(body["results"]) == 1

    def test_handler_post_video_ask_passes_video_id(self, sample_video_ask_event):
        # Arrange
        mock_service = MagicMock()
        mock_service.generate_embedding.return_value = [0.0] * 256
        mock_service.search_similar.return_value = []
        context = MagicMock(aws_request_id="test-123")

        # Act
        with patch.object(handler_module, "service", mock_service):
            handler_module.handler(sample_video_ask_event, context)

        # Assert
        call_kwargs = mock_service.search_similar.call_args
        assert call_kwargs[1]["video_id"] == "hello-my_name_is_wes"

    def test_handler_get_health(self, sample_health_event):
        # Arrange
        context = MagicMock(aws_request_id="test-123")

        # Act
        with patch.object(handler_module, "service", MagicMock()):
            result = handler_module.handler(sample_health_event, context)

        # Assert
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body == {"status": "healthy"}

    def test_handler_get_videos(self, sample_videos_event):
        # Arrange
        mock_service = MagicMock()
        mock_service.list_videos.return_value = [
            {"video_id": "vid-1", "speaker": "Jane", "title": "RAG", "chunk_count": 3},
        ]
        context = MagicMock(aws_request_id="test-123")

        # Act
        with patch.object(handler_module, "service", mock_service):
            result = handler_module.handler(sample_videos_event, context)

        # Assert
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert len(body["videos"]) == 1
        assert body["videos"][0]["video_id"] == "vid-1"

    def test_handler_unknown_route(self):
        # Arrange
        event = {
            "resource": "/unknown",
            "httpMethod": "GET",
            "headers": {},
            "body": None,
        }
        context = MagicMock(aws_request_id="test-123")

        # Act
        with patch.object(handler_module, "service", MagicMock()):
            result = handler_module.handler(event, context)

        # Assert
        assert result["statusCode"] == 404
        body = json.loads(result["body"])
        assert body["error"] == "not found"
