import io
import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from src.services.embedding_service import EmbeddingService
from src.handlers.process_embedding import handler


def _make_bedrock_response(vector):
    body_bytes = json.dumps({"embedding": vector, "inputTextTokenCount": 12}).encode()
    return {"body": io.BytesIO(body_bytes)}


class TestReadChunk:
    def test_read_chunk_parses_json(self, s3_bucket, mock_aws_services, sample_chunk):
        # Arrange
        svc = EmbeddingService()
        svc._s3 = mock_aws_services["s3"]

        # Act
        result = svc.read_chunk(s3_bucket, "chunks/hello-my_name_is_wes/chunk-001.json")

        # Assert
        assert result == sample_chunk

    def test_read_chunk_missing_key_raises(self, s3_bucket, mock_aws_services):
        # Arrange
        svc = EmbeddingService()
        svc._s3 = mock_aws_services["s3"]

        # Act / Assert
        with pytest.raises(ClientError):
            svc.read_chunk(s3_bucket, "chunks/nonexistent/chunk-999.json")


class TestGenerateEmbedding:
    def test_generate_embedding_returns_vector(self):
        # Arrange
        expected_vector = [0.01 * i for i in range(256)]
        mock_bedrock = MagicMock()
        mock_bedrock.invoke_model.return_value = _make_bedrock_response(expected_vector)
        svc = EmbeddingService()
        svc._bedrock = mock_bedrock

        # Act
        result = svc.generate_embedding("Hello world")

        # Assert
        assert result == expected_vector
        assert len(result) == 256

    def test_generate_embedding_passes_correct_params(self):
        # Arrange
        vector = [0.0] * 256
        mock_bedrock = MagicMock()
        mock_bedrock.invoke_model.return_value = _make_bedrock_response(vector)
        svc = EmbeddingService()
        svc._bedrock = mock_bedrock
        svc._dimensions = 256

        # Act
        svc.generate_embedding("Hello world")

        # Assert
        call_kwargs = mock_bedrock.invoke_model.call_args[1]
        assert call_kwargs["modelId"] == "amazon.titan-embed-text-v2:0"
        request_body = json.loads(call_kwargs["body"])
        assert request_body["dimensions"] == 256
        assert request_body["normalize"] is True
        assert request_body["inputText"] == "Hello world"


class TestStoreEmbedding:
    def test_store_embedding_executes_upsert(self, sample_chunk):
        # Arrange
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.cursor.return_value = mock_cursor
        svc = EmbeddingService()
        svc._db_conn = mock_conn
        embedding = [0.01] * 256

        # Act
        svc.store_embedding(sample_chunk, embedding)

        # Assert
        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO video_chunks" in executed_sql
        assert "ON CONFLICT" in executed_sql

    def test_store_embedding_commits(self, sample_chunk):
        # Arrange
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.cursor.return_value = mock_cursor
        svc = EmbeddingService()
        svc._db_conn = mock_conn
        embedding = [0.01] * 256

        # Act
        svc.store_embedding(sample_chunk, embedding)

        # Assert
        mock_conn.commit.assert_called_once()


class TestHandler:
    def test_handler_processes_single_record(self, sample_sqs_event, sample_chunk):
        # Arrange
        mock_context = MagicMock()
        mock_context.aws_request_id = "test-request-id"
        embedding = [0.01] * 256

        with patch("src.handlers.process_embedding.service") as mock_service:
            mock_service.read_chunk.return_value = sample_chunk
            mock_service.generate_embedding.return_value = embedding

            # Act
            handler(sample_sqs_event, mock_context)

        # Assert
        mock_service.read_chunk.assert_called_once()
        mock_service.generate_embedding.assert_called_once_with(sample_chunk["text"])
        mock_service.store_embedding.assert_called_once_with(sample_chunk, embedding)

    def test_handler_processes_multiple_records(self, sample_chunk):
        # Arrange
        mock_context = MagicMock()
        mock_context.aws_request_id = "test-request-id"
        embedding = [0.01] * 256

        two_record_event = {
            "Records": [
                {
                    "body": json.dumps({
                        "chunk_s3_key": f"chunks/vid/chunk-00{i}.json",
                        "bucket": "test-bucket",
                        "video_id": "vid",
                        "speaker": None,
                        "title": None,
                    })
                }
                for i in range(1, 3)
            ]
        }

        with patch("src.handlers.process_embedding.service") as mock_service:
            mock_service.read_chunk.return_value = sample_chunk
            mock_service.generate_embedding.return_value = embedding

            # Act
            handler(two_record_event, mock_context)

        # Assert
        assert mock_service.read_chunk.call_count == 2
        assert mock_service.generate_embedding.call_count == 2
        assert mock_service.store_embedding.call_count == 2
