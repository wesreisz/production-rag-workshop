import io
import json
from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError

from src.services.embedding_service import EmbeddingService


class TestReadChunk:
    def test_read_chunk_parses_json(self, s3_bucket, sample_chunk):
        # Arrange
        s3 = boto3.client("s3", region_name="us-east-1")
        key = "chunks/hello-my_name_is_wes/chunk-001.json"
        s3.put_object(Bucket=s3_bucket, Key=key, Body=json.dumps(sample_chunk))
        service = EmbeddingService()

        # Act
        result = service.read_chunk(s3_bucket, key)

        # Assert
        assert result == sample_chunk

    def test_read_chunk_missing_key_raises(self, s3_bucket):
        # Arrange
        service = EmbeddingService()

        # Act / Assert
        with pytest.raises(ClientError):
            service.read_chunk(s3_bucket, "nonexistent/key.json")


class TestGenerateEmbedding:
    def test_generate_embedding_returns_vector(self, mock_aws_services):
        # Arrange
        fake_embedding = [0.01 * i for i in range(256)]
        mock_response = {
            "body": io.BytesIO(json.dumps({
                "embedding": fake_embedding,
                "inputTextTokenCount": 12,
            }).encode()),
        }
        service = EmbeddingService()
        service._bedrock = MagicMock()
        service._bedrock.invoke_model.return_value = mock_response

        # Act
        result = service.generate_embedding("Hello, my name is Wes.")

        # Assert
        assert result == fake_embedding
        assert len(result) == 256

    def test_generate_embedding_passes_correct_params(self, mock_aws_services):
        # Arrange
        fake_embedding = [0.0] * 256
        mock_response = {
            "body": io.BytesIO(json.dumps({
                "embedding": fake_embedding,
                "inputTextTokenCount": 5,
            }).encode()),
        }
        service = EmbeddingService()
        service._bedrock = MagicMock()
        service._bedrock.invoke_model.return_value = mock_response

        # Act
        service.generate_embedding("test text")

        # Assert
        call_kwargs = service._bedrock.invoke_model.call_args[1]
        assert call_kwargs["modelId"] == "amazon.titan-embed-text-v2:0"
        assert call_kwargs["contentType"] == "application/json"
        assert call_kwargs["accept"] == "application/json"
        body = json.loads(call_kwargs["body"])
        assert body["inputText"] == "test text"
        assert body["dimensions"] == 256
        assert body["normalize"] is True


class TestStoreEmbedding:
    def test_store_embedding_executes_upsert(self, mock_aws_services, sample_chunk):
        # Arrange
        service = EmbeddingService()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        service.get_db_connection = MagicMock(return_value=mock_conn)
        embedding = [0.01 * i for i in range(256)]

        # Act
        service.store_embedding(sample_chunk, embedding)

        # Assert
        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO video_chunks" in sql
        assert "ON CONFLICT (chunk_id) DO UPDATE" in sql
        params = mock_cursor.execute.call_args[0][1]
        assert params[0] == sample_chunk["chunk_id"]
        assert params[1] == sample_chunk["video_id"]
        assert params[2] == sample_chunk["sequence"]
        assert params[3] == sample_chunk["text"]
        assert params[5] == sample_chunk["metadata"]["speaker"]
        assert params[6] == sample_chunk["metadata"]["title"]
        assert params[7] == sample_chunk["start_time"]
        assert params[8] == sample_chunk["end_time"]
        assert params[9] == sample_chunk["metadata"]["source_s3_key"]

    def test_store_embedding_commits(self, mock_aws_services, sample_chunk):
        # Arrange
        service = EmbeddingService()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        service.get_db_connection = MagicMock(return_value=mock_conn)
        embedding = [0.0] * 256

        # Act
        service.store_embedding(sample_chunk, embedding)

        # Assert
        mock_conn.commit.assert_called_once()


class TestHandler:
    @patch("src.handlers.process_embedding.service")
    def test_handler_processes_single_record(self, mock_service, sample_sqs_event, sample_chunk):
        # Arrange
        from src.handlers.process_embedding import handler

        mock_service.read_chunk.return_value = sample_chunk
        mock_service.generate_embedding.return_value = [0.0] * 256

        # Act
        handler(sample_sqs_event, None)

        # Assert
        mock_service.read_chunk.assert_called_once_with(
            "test-bucket", "chunks/hello-my_name_is_wes/chunk-001.json"
        )
        mock_service.generate_embedding.assert_called_once_with(sample_chunk["text"])
        mock_service.store_embedding.assert_called_once_with(
            sample_chunk, [0.0] * 256
        )

    @patch("src.handlers.process_embedding.service")
    def test_handler_processes_multiple_records(self, mock_service, sample_sqs_event, sample_chunk):
        # Arrange
        from src.handlers.process_embedding import handler

        second_record = dict(sample_sqs_event["Records"][0])
        second_record["body"] = json.dumps({
            "chunk_s3_key": "chunks/hello-my_name_is_wes/chunk-002.json",
            "bucket": "test-bucket",
            "video_id": "hello-my_name_is_wes",
            "speaker": "Jane Doe",
            "title": "Building RAG Systems",
        })
        sample_sqs_event["Records"].append(second_record)

        mock_service.read_chunk.return_value = sample_chunk
        mock_service.generate_embedding.return_value = [0.0] * 256

        # Act
        handler(sample_sqs_event, None)

        # Assert
        assert mock_service.read_chunk.call_count == 2
        assert mock_service.generate_embedding.call_count == 2
        assert mock_service.store_embedding.call_count == 2
