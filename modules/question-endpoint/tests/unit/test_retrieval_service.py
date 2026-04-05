import io
import json
from unittest.mock import MagicMock, patch

import pytest

from src.services.retrieval_service import RetrievalService
from src.handlers.question import handler


def _make_bedrock_response(vector):
    body_bytes = json.dumps({"embedding": vector}).encode()
    return {"body": io.BytesIO(body_bytes)}


def _make_cursor(rows):
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    return cursor


def _make_conn(cursor):
    conn = MagicMock()
    conn.closed = False
    conn.cursor.return_value = cursor
    return conn


SAMPLE_ROW = (
    "hello-my_name_is_wes-chunk-001",
    "hello-my_name_is_wes",
    "RAG stands for retrieval augmented generation.",
    "Jane Doe",
    "Building RAG Systems",
    0.0,
    45.2,
    "uploads/hello-my_name_is_wes.mp3",
    0.89,
)


class TestGenerateEmbedding:
    def test_generate_embedding_returns_vector(self):
        # Arrange
        expected_vector = [0.01 * i for i in range(256)]
        svc = RetrievalService()
        svc._bedrock = MagicMock()
        svc._bedrock.invoke_model.return_value = _make_bedrock_response(expected_vector)

        # Act
        result = svc.generate_embedding("What is RAG?")

        # Assert
        assert result == expected_vector
        assert len(result) == 256

    def test_generate_embedding_passes_correct_params(self):
        # Arrange
        vector = [0.0] * 256
        svc = RetrievalService()
        svc._bedrock = MagicMock()
        svc._bedrock.invoke_model.return_value = _make_bedrock_response(vector)
        svc._dimensions = 256

        # Act
        svc.generate_embedding("What is RAG?")

        # Assert
        call_kwargs = svc._bedrock.invoke_model.call_args[1]
        assert call_kwargs["modelId"] == "amazon.titan-embed-text-v2:0"
        request_body = json.loads(call_kwargs["body"])
        assert request_body["dimensions"] == 256
        assert request_body["normalize"] is True
        assert request_body["inputText"] == "What is RAG?"


class TestSearchSimilar:
    def test_search_similar_returns_ranked_results(self):
        # Arrange
        svc = RetrievalService()
        cursor = _make_cursor([SAMPLE_ROW])
        svc._db_conn = _make_conn(cursor)
        embedding = [0.01] * 256

        # Act
        results = svc.search_similar(embedding, top_k=5)

        # Assert
        assert len(results) == 1
        assert results[0]["chunk_id"] == "hello-my_name_is_wes-chunk-001"
        assert results[0]["similarity"] == 0.89

    def test_search_similar_with_speaker_filter(self):
        # Arrange
        svc = RetrievalService()
        cursor = _make_cursor([SAMPLE_ROW])
        svc._db_conn = _make_conn(cursor)
        embedding = [0.01] * 256

        # Act
        svc.search_similar(embedding, top_k=5, speaker="Jane Doe")

        # Assert
        executed_sql = cursor.execute.call_args[0][0]
        assert "WHERE speaker" in executed_sql

    def test_search_similar_without_filter(self):
        # Arrange
        svc = RetrievalService()
        cursor = _make_cursor([SAMPLE_ROW])
        svc._db_conn = _make_conn(cursor)
        embedding = [0.01] * 256

        # Act
        svc.search_similar(embedding, top_k=5)

        # Assert
        executed_sql = cursor.execute.call_args[0][0]
        assert "WHERE" not in executed_sql

    def test_search_similar_filters_below_threshold(self):
        # Arrange
        low_similarity_row = SAMPLE_ROW[:8] + (0.3,)
        high_similarity_row = SAMPLE_ROW[:8] + (0.9,)
        svc = RetrievalService()
        cursor = _make_cursor([low_similarity_row, high_similarity_row])
        svc._db_conn = _make_conn(cursor)
        embedding = [0.01] * 256

        # Act
        results = svc.search_similar(embedding, top_k=5, similarity_threshold=0.5)

        # Assert
        assert len(results) == 1
        assert results[0]["similarity"] == 0.9

    def test_search_similar_with_video_id_filter(self):
        # Arrange
        svc = RetrievalService()
        cursor = _make_cursor([SAMPLE_ROW])
        svc._db_conn = _make_conn(cursor)
        embedding = [0.01] * 256

        # Act
        svc.search_similar(embedding, top_k=5, video_id="hello-my_name_is_wes")

        # Assert
        executed_sql = cursor.execute.call_args[0][0]
        assert "WHERE video_id" in executed_sql


class TestListVideos:
    def test_list_videos_returns_aggregated(self):
        # Arrange
        video_row = ("hello-my_name_is_wes", "Jane Doe", "Building RAG Systems", 3)
        svc = RetrievalService()
        cursor = _make_cursor([video_row])
        svc._db_conn = _make_conn(cursor)

        # Act
        results = svc.list_videos()

        # Assert
        assert len(results) == 1
        assert results[0]["video_id"] == "hello-my_name_is_wes"
        assert results[0]["speaker"] == "Jane Doe"
        assert results[0]["title"] == "Building RAG Systems"
        assert results[0]["chunk_count"] == 3


class TestHandler:
    def test_handler_post_ask_returns_results(self, aws_credentials, sample_ask_event):
        # Arrange
        mock_results = [{"chunk_id": "c-001", "similarity": 0.89}]
        with patch("src.handlers.question.service") as mock_service:
            mock_service.generate_embedding.return_value = [0.01] * 256
            mock_service.search_similar.return_value = mock_results

            # Act
            response = handler(sample_ask_event, None)

        # Assert
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["question"] == "What is RAG?"
        assert body["results"] == mock_results

    def test_handler_post_ask_missing_question(self, aws_credentials):
        # Arrange
        event = {
            "resource": "/ask",
            "httpMethod": "POST",
            "body": json.dumps({"question": ""}),
        }

        # Act
        response = handler(event, None)

        # Assert
        assert response["statusCode"] == 400
        assert json.loads(response["body"]) == {"error": "question is required"}

    def test_handler_post_video_ask_returns_results(self, aws_credentials, sample_video_ask_event):
        # Arrange
        mock_results = [{"chunk_id": "c-001", "similarity": 0.89}]
        with patch("src.handlers.question.service") as mock_service:
            mock_service.generate_embedding.return_value = [0.01] * 256
            mock_service.search_similar.return_value = mock_results

            # Act
            response = handler(sample_video_ask_event, None)

        # Assert
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["video_id"] == "hello-my_name_is_wes"
        assert body["question"] == "What is RAG?"
        assert body["results"] == mock_results

    def test_handler_post_video_ask_passes_video_id(self, aws_credentials, sample_video_ask_event):
        # Arrange
        with patch("src.handlers.question.service") as mock_service:
            mock_service.generate_embedding.return_value = [0.01] * 256
            mock_service.search_similar.return_value = []

            # Act
            handler(sample_video_ask_event, None)

        # Assert
        call_kwargs = mock_service.search_similar.call_args[1]
        assert call_kwargs["video_id"] == "hello-my_name_is_wes"

    def test_handler_get_health(self, sample_health_event):
        # Arrange / Act
        response = handler(sample_health_event, None)

        # Assert
        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == {"status": "healthy"}

    def test_handler_get_videos(self, aws_credentials, sample_videos_event):
        # Arrange
        mock_videos = [{"video_id": "v-001", "chunk_count": 3}]
        with patch("src.handlers.question.service") as mock_service:
            mock_service.list_videos.return_value = mock_videos

            # Act
            response = handler(sample_videos_event, None)

        # Assert
        assert response["statusCode"] == 200
        assert json.loads(response["body"]) == {"videos": mock_videos}

    def test_handler_unknown_route(self):
        # Arrange
        event = {
            "resource": "/unknown",
            "httpMethod": "GET",
            "body": None,
        }

        # Act
        response = handler(event, None)

        # Assert
        assert response["statusCode"] == 404
