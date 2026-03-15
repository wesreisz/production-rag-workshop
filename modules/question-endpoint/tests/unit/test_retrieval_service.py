import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_embedding():
    return [0.01 * i for i in range(256)]


@pytest.fixture
def fake_db_rows():
    return [
        (
            "vid1-chunk-001", "vid1", "Text about error handling", "Jane Doe",
            "Building RAG", 10.0, 45.2, "uploads/vid1.mp3", 0.92,
        ),
        (
            "vid1-chunk-002", "vid1", "Another chunk about testing", "Jane Doe",
            "Building RAG", 50.0, 90.1, "uploads/vid1.mp3", 0.85,
        ),
        (
            "vid1-chunk-003", "vid1", "Low relevance chunk", "Jane Doe",
            "Building RAG", 100.0, 130.0, "uploads/vid1.mp3", 0.30,
        ),
    ]


class TestGenerateEmbedding:
    def test_generate_embedding_returns_vector(self, aws_credentials, fake_embedding):
        # Arrange
        response_body = json.dumps({"embedding": fake_embedding})
        mock_bedrock = MagicMock()
        mock_bedrock.invoke_model.return_value = {
            "body": BytesIO(response_body.encode()),
        }

        with patch("src.services.retrieval_service.boto3") as mock_boto3:
            mock_boto3.client.side_effect = lambda svc: (
                mock_bedrock if svc == "bedrock-runtime" else MagicMock()
            )
            from src.services.retrieval_service import RetrievalService
            service = RetrievalService()
            service._bedrock = mock_bedrock

            # Act
            result = service.generate_embedding("What is RAG?")

            # Assert
            assert isinstance(result, list)
            assert len(result) == 256

    def test_generate_embedding_passes_correct_params(self, aws_credentials, fake_embedding):
        # Arrange
        response_body = json.dumps({"embedding": fake_embedding})
        mock_bedrock = MagicMock()
        mock_bedrock.invoke_model.return_value = {
            "body": BytesIO(response_body.encode()),
        }

        with patch("src.services.retrieval_service.boto3") as mock_boto3:
            mock_boto3.client.side_effect = lambda svc: (
                mock_bedrock if svc == "bedrock-runtime" else MagicMock()
            )
            from src.services.retrieval_service import RetrievalService
            service = RetrievalService()
            service._bedrock = mock_bedrock

            # Act
            service.generate_embedding("What is RAG?")

            # Assert
            call_args = mock_bedrock.invoke_model.call_args
            assert call_args.kwargs["modelId"] == "amazon.titan-embed-text-v2:0"
            body = json.loads(call_args.kwargs["body"])
            assert body["inputText"] == "What is RAG?"
            assert body["dimensions"] == 256
            assert body["normalize"] is True


class TestSearchSimilar:
    def test_search_similar_returns_ranked_results(self, aws_credentials, fake_db_rows):
        # Arrange
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = fake_db_rows
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.closed = 0

        with patch("src.services.retrieval_service.boto3") as mock_boto3:
            mock_boto3.client.side_effect = lambda svc: MagicMock()
            from src.services.retrieval_service import RetrievalService
            service = RetrievalService()
            service._db_conn = mock_conn

            embedding = [0.01] * 256

            # Act
            results = service.search_similar(embedding, top_k=5)

            # Assert
            assert isinstance(results, list)
            assert len(results) == 3
            assert results[0]["chunk_id"] == "vid1-chunk-001"
            assert results[0]["similarity"] == 0.92

    def test_search_similar_with_speaker_filter(self, aws_credentials, fake_db_rows):
        # Arrange
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = fake_db_rows[:1]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.closed = 0

        with patch("src.services.retrieval_service.boto3") as mock_boto3:
            mock_boto3.client.side_effect = lambda svc: MagicMock()
            from src.services.retrieval_service import RetrievalService
            service = RetrievalService()
            service._db_conn = mock_conn

            embedding = [0.01] * 256

            # Act
            service.search_similar(embedding, top_k=5, speaker="Jane Doe")

            # Assert
            executed_sql = mock_cursor.execute.call_args[0][0]
            assert "WHERE speaker = %s" in executed_sql

    def test_search_similar_without_filter(self, aws_credentials, fake_db_rows):
        # Arrange
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = fake_db_rows
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.closed = 0

        with patch("src.services.retrieval_service.boto3") as mock_boto3:
            mock_boto3.client.side_effect = lambda svc: MagicMock()
            from src.services.retrieval_service import RetrievalService
            service = RetrievalService()
            service._db_conn = mock_conn

            embedding = [0.01] * 256

            # Act
            service.search_similar(embedding, top_k=5)

            # Assert
            executed_sql = mock_cursor.execute.call_args[0][0]
            assert "WHERE" not in executed_sql

    def test_search_similar_filters_below_threshold(self, aws_credentials, fake_db_rows):
        # Arrange
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = fake_db_rows
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.closed = 0

        with patch("src.services.retrieval_service.boto3") as mock_boto3:
            mock_boto3.client.side_effect = lambda svc: MagicMock()
            from src.services.retrieval_service import RetrievalService
            service = RetrievalService()
            service._db_conn = mock_conn

            embedding = [0.01] * 256

            # Act
            results = service.search_similar(
                embedding, top_k=5, similarity_threshold=0.5,
            )

            # Assert
            assert len(results) == 2
            assert all(r["similarity"] >= 0.5 for r in results)

    def test_search_similar_with_video_id_filter(self, aws_credentials, fake_db_rows):
        # Arrange
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = fake_db_rows[:1]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.closed = 0

        with patch("src.services.retrieval_service.boto3") as mock_boto3:
            mock_boto3.client.side_effect = lambda svc: MagicMock()
            from src.services.retrieval_service import RetrievalService
            service = RetrievalService()
            service._db_conn = mock_conn

            embedding = [0.01] * 256

            # Act
            service.search_similar(embedding, top_k=5, video_id="vid1")

            # Assert
            executed_sql = mock_cursor.execute.call_args[0][0]
            assert "WHERE video_id = %s" in executed_sql


class TestListVideos:
    def test_list_videos_returns_aggregated(self, aws_credentials):
        # Arrange
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("vid1", "Jane Doe", "Building RAG", 3),
            ("vid2", "John Smith", "Intro to AI", 5),
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.closed = 0

        with patch("src.services.retrieval_service.boto3") as mock_boto3:
            mock_boto3.client.side_effect = lambda svc: MagicMock()
            from src.services.retrieval_service import RetrievalService
            service = RetrievalService()
            service._db_conn = mock_conn

            # Act
            results = service.list_videos()

            # Assert
            assert len(results) == 2
            assert results[0]["video_id"] == "vid1"
            assert results[0]["chunk_count"] == 3
            assert results[1]["video_id"] == "vid2"


class TestHandler:
    def test_handler_post_ask_returns_results(
        self, aws_credentials, sample_ask_event, fake_embedding,
    ):
        # Arrange
        mock_results = [
            {
                "chunk_id": "vid1-chunk-001",
                "video_id": "vid1",
                "text": "Text about error handling",
                "similarity": 0.92,
                "speaker": "Jane Doe",
                "title": "Building RAG",
                "start_time": 10.0,
                "end_time": 45.2,
                "source_s3_key": "uploads/vid1.mp3",
            }
        ]

        with patch("src.handlers.question.service") as mock_service:
            mock_service.generate_embedding.return_value = fake_embedding
            mock_service.search_similar.return_value = mock_results
            from src.handlers.question import handler

            # Act
            response = handler(sample_ask_event, None)

            # Assert
            assert response["statusCode"] == 200
            body = json.loads(response["body"])
            assert body["question"] == "What is RAG?"
            assert len(body["results"]) == 1

    def test_handler_post_ask_missing_question(self, aws_credentials):
        # Arrange
        event = {
            "resource": "/ask",
            "path": "/ask",
            "httpMethod": "POST",
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"question": ""}),
            "isBase64Encoded": False,
        }

        with patch("src.handlers.question.service") as mock_service:
            from src.handlers.question import handler

            # Act
            response = handler(event, None)

            # Assert
            assert response["statusCode"] == 400
            body = json.loads(response["body"])
            assert body["error"] == "question is required"

    def test_handler_post_video_ask_returns_results(
        self, aws_credentials, sample_video_ask_event, fake_embedding,
    ):
        # Arrange
        mock_results = [
            {
                "chunk_id": "hello-my_name_is_wes-chunk-001",
                "video_id": "hello-my_name_is_wes",
                "text": "Text about error handling",
                "similarity": 0.92,
                "speaker": "Jane Doe",
                "title": "Building RAG",
                "start_time": 10.0,
                "end_time": 45.2,
                "source_s3_key": "uploads/hello-my_name_is_wes.mp3",
            }
        ]

        with patch("src.handlers.question.service") as mock_service:
            mock_service.generate_embedding.return_value = fake_embedding
            mock_service.search_similar.return_value = mock_results
            from src.handlers.question import handler

            # Act
            response = handler(sample_video_ask_event, None)

            # Assert
            assert response["statusCode"] == 200
            body = json.loads(response["body"])
            assert body["video_id"] == "hello-my_name_is_wes"
            assert body["question"] == "What is this about?"
            assert len(body["results"]) == 1

    def test_handler_post_video_ask_passes_video_id(
        self, aws_credentials, sample_video_ask_event, fake_embedding,
    ):
        # Arrange
        with patch("src.handlers.question.service") as mock_service:
            mock_service.generate_embedding.return_value = fake_embedding
            mock_service.search_similar.return_value = []
            from src.handlers.question import handler

            # Act
            handler(sample_video_ask_event, None)

            # Assert
            call_kwargs = mock_service.search_similar.call_args
            assert call_kwargs.kwargs.get("video_id") == "hello-my_name_is_wes" or \
                (len(call_kwargs.args) > 4 and call_kwargs.args[4] == "hello-my_name_is_wes")

    def test_handler_get_health(self, aws_credentials, sample_health_event):
        # Arrange
        with patch("src.handlers.question.service"):
            from src.handlers.question import handler

            # Act
            response = handler(sample_health_event, None)

            # Assert
            assert response["statusCode"] == 200
            body = json.loads(response["body"])
            assert body["status"] == "healthy"

    def test_handler_get_videos(self, aws_credentials, sample_videos_event):
        # Arrange
        mock_videos = [
            {"video_id": "vid1", "speaker": "Jane", "title": "RAG", "chunk_count": 3},
        ]

        with patch("src.handlers.question.service") as mock_service:
            mock_service.list_videos.return_value = mock_videos
            from src.handlers.question import handler

            # Act
            response = handler(sample_videos_event, None)

            # Assert
            assert response["statusCode"] == 200
            body = json.loads(response["body"])
            assert len(body["videos"]) == 1

    def test_handler_unknown_route(self, aws_credentials):
        # Arrange
        event = {
            "resource": "/unknown",
            "path": "/unknown",
            "httpMethod": "GET",
            "headers": {},
            "body": None,
            "isBase64Encoded": False,
        }

        with patch("src.handlers.question.service"):
            from src.handlers.question import handler

            # Act
            response = handler(event, None)

            # Assert
            assert response["statusCode"] == 404
