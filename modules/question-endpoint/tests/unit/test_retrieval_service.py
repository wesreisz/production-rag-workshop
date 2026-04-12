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


def _make_fetchone_cursor(row):
    cursor = MagicMock()
    cursor.fetchone.return_value = row
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

        # Assert — base SQL has no video_id or speaker WHERE clause filter
        executed_sql = cursor.execute.call_args[0][0]
        assert "video_id = %(video_id)s" not in executed_sql
        assert "speaker = %(speaker)s" not in executed_sql

    def test_search_respects_similarity_threshold(self):
        # Arrange — mock cursor simulates DB returning only rows above threshold
        high_similarity_row = SAMPLE_ROW[:8] + (0.9,)
        svc = RetrievalService()
        cursor = _make_cursor([high_similarity_row])
        svc._db_conn = _make_conn(cursor)
        embedding = [0.01] * 256

        # Act
        results = svc.search_similar(embedding, top_k=5, similarity_threshold=0.5)

        # Assert — all rows returned by cursor are passed through
        assert len(results) == 1
        assert results[0]["similarity"] == 0.9

    def test_search_threshold_in_sql_params(self):
        # Arrange
        svc = RetrievalService()
        cursor = _make_cursor([SAMPLE_ROW])
        svc._db_conn = _make_conn(cursor)
        embedding = [0.01] * 256

        # Act
        svc.search_similar(embedding, top_k=5, similarity_threshold=0.75)

        # Assert — similarity_threshold is passed as a SQL parameter, not filtered in Python
        executed_params = cursor.execute.call_args[0][1]
        assert isinstance(executed_params, dict)
        assert executed_params["similarity_threshold"] == 0.75
        assert executed_params["top_k"] == 5

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


class TestGetVideoMetadata:
    def test_get_video_metadata_returns_dict(self):
        # Arrange
        svc = RetrievalService()
        cursor = _make_fetchone_cursor(("uploads/hello-my_name_is_wes.mp3", "Wesley Reisz", "Building RAG Systems"))
        svc._db_conn = _make_conn(cursor)

        # Act
        result = svc.get_video_metadata("hello-my_name_is_wes")

        # Assert
        assert result["source_s3_key"] == "uploads/hello-my_name_is_wes.mp3"
        assert result["speaker"] == "Wesley Reisz"
        assert result["title"] == "Building RAG Systems"

    def test_get_video_metadata_not_found(self):
        # Arrange
        svc = RetrievalService()
        cursor = _make_fetchone_cursor(None)
        svc._db_conn = _make_conn(cursor)

        # Act
        result = svc.get_video_metadata("nonexistent")

        # Assert
        assert result is None


class TestGetChunkMetadata:
    def test_get_chunk_metadata_returns_dict(self):
        # Arrange
        svc = RetrievalService()
        cursor = _make_fetchone_cursor((
            "uploads/hello-my_name_is_wes.mp3",
            "hello-my_name_is_wes",
            "Wesley Reisz",
            "Building RAG Systems",
            234.5,
            279.8,
        ))
        svc._db_conn = _make_conn(cursor)

        # Act
        result = svc.get_chunk_metadata("hello-my_name_is_wes-chunk-001")

        # Assert
        assert result["source_s3_key"] == "uploads/hello-my_name_is_wes.mp3"
        assert result["video_id"] == "hello-my_name_is_wes"
        assert result["speaker"] == "Wesley Reisz"
        assert result["title"] == "Building RAG Systems"
        assert result["start_time"] == 234.5
        assert result["end_time"] == 279.8

    def test_get_chunk_metadata_not_found(self):
        # Arrange
        svc = RetrievalService()
        cursor = _make_fetchone_cursor(None)
        svc._db_conn = _make_conn(cursor)

        # Act
        result = svc.get_chunk_metadata("nonexistent-chunk")

        # Assert
        assert result is None


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

    def test_handler_presign_returns_url(self, aws_credentials, sample_presign_event):
        # Arrange
        fake_metadata = {"source_s3_key": "uploads/hello-my_name_is_wes.mp3", "speaker": "Wesley Reisz", "title": "Building RAG Systems"}
        fake_url = "https://example.s3.amazonaws.com/uploads/hello-my_name_is_wes.mp3?X-Amz-Signature=abc"
        with patch("src.handlers.question.service") as mock_service, \
             patch("src.handlers.question.s3_client") as mock_s3:
            mock_service.get_video_metadata.return_value = fake_metadata
            mock_s3.generate_presigned_url.return_value = fake_url

            # Act
            response = handler(sample_presign_event, None)

        # Assert
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["presigned_url"] == fake_url
        assert body["video_id"] == "hello-my_name_is_wes"
        assert body["expires_in"] == 3600

    def test_handler_presign_with_chunk_id(self, aws_credentials, sample_presign_with_chunk_event):
        # Arrange
        fake_metadata = {
            "source_s3_key": "uploads/hello-my_name_is_wes.mp3",
            "video_id": "hello-my_name_is_wes",
            "speaker": "Wesley Reisz",
            "title": "Building RAG Systems",
            "start_time": 234.5,
            "end_time": 279.8,
        }
        fake_url = "https://example.s3.amazonaws.com/uploads/hello-my_name_is_wes.mp3?X-Amz-Signature=abc"
        with patch("src.handlers.question.service") as mock_service, \
             patch("src.handlers.question.s3_client") as mock_s3:
            mock_service.get_chunk_metadata.return_value = fake_metadata
            mock_s3.generate_presigned_url.return_value = fake_url

            # Act
            response = handler(sample_presign_with_chunk_event, None)

        # Assert
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["start_time"] == 234.5
        assert body["end_time"] == 279.8

    def test_handler_presign_video_not_found(self, aws_credentials, sample_presign_event):
        # Arrange
        with patch("src.handlers.question.service") as mock_service:
            mock_service.get_video_metadata.return_value = None

            # Act
            response = handler(sample_presign_event, None)

        # Assert
        assert response["statusCode"] == 404
        assert json.loads(response["body"]) == {"error": "video not found"}

    def test_handler_presign_chunk_not_found(self, aws_credentials, sample_presign_with_chunk_event):
        # Arrange
        with patch("src.handlers.question.service") as mock_service:
            mock_service.get_chunk_metadata.return_value = None

            # Act
            response = handler(sample_presign_with_chunk_event, None)

        # Assert
        assert response["statusCode"] == 404
        assert json.loads(response["body"]) == {"error": "chunk not found"}
