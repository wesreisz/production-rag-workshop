import io
import json
import os
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from botocore.response import StreamingBody

os.environ.setdefault("SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123456789012:secret:test-secret")
os.environ.setdefault("DB_NAME", "ragdb")
os.environ.setdefault("EMBEDDING_DIMENSIONS", "256")

from src.services.embedding_service import EmbeddingService

with patch("boto3.client"):
    import src.handlers.process_embedding as handler_module


class TestReadChunk:
    def test_read_chunk_parses_json(self, mock_aws_services, s3_bucket, sample_chunk):
        # Arrange
        mock_aws_services["s3"].put_object(
            Bucket=s3_bucket,
            Key="chunks/hello-my_name_is_wes/chunk-001.json",
            Body=json.dumps(sample_chunk),
        )
        service = EmbeddingService(s3_client=mock_aws_services["s3"])

        # Act
        result = service.read_chunk(s3_bucket, "chunks/hello-my_name_is_wes/chunk-001.json")

        # Assert
        assert result == sample_chunk
        assert result["chunk_id"] == "hello-my_name_is_wes-chunk-001"
        assert result["text"] == sample_chunk["text"]

    def test_read_chunk_missing_key_raises(self, mock_aws_services, s3_bucket):
        # Arrange
        service = EmbeddingService(s3_client=mock_aws_services["s3"])

        # Act & Assert
        with pytest.raises(ClientError):
            service.read_chunk(s3_bucket, "chunks/nonexistent/chunk-999.json")


class TestGenerateEmbedding:
    def _make_bedrock_response(self, embedding):
        body_bytes = json.dumps({
            "embedding": embedding,
            "inputTextTokenCount": 487,
        }).encode("utf-8")
        return {
            "body": StreamingBody(io.BytesIO(body_bytes), len(body_bytes)),
        }

    def test_generate_embedding_returns_vector(self, aws_credentials):
        # Arrange
        expected_embedding = [float(i) * 0.01 for i in range(256)]
        mock_bedrock = MagicMock()
        mock_bedrock.invoke_model.return_value = self._make_bedrock_response(expected_embedding)
        service = EmbeddingService(
            s3_client=MagicMock(),
            bedrock_client=mock_bedrock,
            secretsmanager_client=MagicMock(),
        )

        # Act
        result = service.generate_embedding("Hello, my name is Wes.")

        # Assert
        assert result == expected_embedding
        assert len(result) == 256
        assert all(isinstance(v, float) for v in result)

    def test_generate_embedding_passes_correct_params(self, aws_credentials):
        # Arrange
        mock_bedrock = MagicMock()
        mock_bedrock.invoke_model.return_value = self._make_bedrock_response([0.0] * 256)
        service = EmbeddingService(
            s3_client=MagicMock(),
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


class TestStoreEmbedding:
    def test_store_embedding_executes_upsert(self, aws_credentials, sample_chunk):
        # Arrange
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        service = EmbeddingService.__new__(EmbeddingService)
        service.get_db_connection = MagicMock(return_value=mock_conn)
        embedding = [0.01, -0.02, 0.03]

        # Act
        service.store_embedding(sample_chunk, embedding)

        # Assert
        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        params = mock_cursor.execute.call_args[0][1]
        assert "INSERT INTO video_chunks" in sql
        assert "ON CONFLICT (chunk_id) DO UPDATE" in sql
        assert params[0] == "hello-my_name_is_wes-chunk-001"
        assert params[1] == "hello-my_name_is_wes"
        assert params[2] == 1
        assert params[3] == sample_chunk["text"]
        assert params[4] == str(embedding)
        assert params[5] == "Jane Doe"
        assert params[6] == "Building RAG Systems"
        assert params[7] == 0.0
        assert params[8] == 45.2
        assert params[9] == "uploads/hello-my_name_is_wes.mp3"

    def test_store_embedding_commits(self, aws_credentials, sample_chunk):
        # Arrange
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        service = EmbeddingService.__new__(EmbeddingService)
        service.get_db_connection = MagicMock(return_value=mock_conn)
        embedding = [0.01, -0.02, 0.03]

        # Act
        service.store_embedding(sample_chunk, embedding)

        # Assert
        mock_conn.commit.assert_called_once()


class TestHandler:
    def test_handler_processes_single_record(self, sample_sqs_event, sample_chunk):
        # Arrange
        mock_service = MagicMock()
        mock_service.read_chunk.return_value = sample_chunk
        mock_service.generate_embedding.return_value = [0.0] * 256
        context = MagicMock(aws_request_id="test-123")

        # Act
        with patch.object(handler_module, "service", mock_service):
            handler_module.handler(sample_sqs_event, context)

        # Assert
        mock_service.read_chunk.assert_called_once_with(
            "test-bucket", "chunks/hello-my_name_is_wes/chunk-001.json"
        )
        mock_service.generate_embedding.assert_called_once_with(sample_chunk["text"])
        mock_service.store_embedding.assert_called_once_with(sample_chunk, [0.0] * 256)

    def test_handler_processes_multiple_records(self, sample_chunk):
        # Arrange
        event = {
            "Records": [
                {
                    "messageId": "msg-1",
                    "body": json.dumps({
                        "chunk_s3_key": "chunks/vid/chunk-001.json",
                        "bucket": "test-bucket",
                        "video_id": "vid",
                    }),
                },
                {
                    "messageId": "msg-2",
                    "body": json.dumps({
                        "chunk_s3_key": "chunks/vid/chunk-002.json",
                        "bucket": "test-bucket",
                        "video_id": "vid",
                    }),
                },
            ]
        }
        mock_service = MagicMock()
        mock_service.read_chunk.return_value = sample_chunk
        mock_service.generate_embedding.return_value = [0.0] * 256
        context = MagicMock(aws_request_id="test-456")

        # Act
        with patch.object(handler_module, "service", mock_service):
            handler_module.handler(event, context)

        # Assert
        assert mock_service.read_chunk.call_count == 2
        assert mock_service.generate_embedding.call_count == 2
        assert mock_service.store_embedding.call_count == 2
