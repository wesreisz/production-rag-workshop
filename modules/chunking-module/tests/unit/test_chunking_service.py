import json
from unittest.mock import MagicMock

import pytest

from src.services.chunking_service import ChunkingService


class TestParseTimedWords:
    def test_parse_timed_words_attaches_punctuation(self, sample_transcript):
        # Arrange
        svc = ChunkingService(s3_client=MagicMock(), sqs_client=MagicMock())

        # Act
        result = svc.parse_timed_words(sample_transcript)

        # Assert
        assert result[0]["text"] == "Hello,"
        assert result[0]["start_time"] == 0.0
        assert result[0]["end_time"] == 0.43
        assert result[4]["text"] == "Wes."
        assert len(result) == 13

    def test_parse_timed_words_empty_items(self):
        # Arrange
        svc = ChunkingService(s3_client=MagicMock(), sqs_client=MagicMock())
        transcript = {"results": {"items": []}}

        # Act
        result = svc.parse_timed_words(transcript)

        # Assert
        assert result == []


class TestBuildSentences:
    def test_build_sentences_splits_on_period(self, sample_transcript):
        # Arrange
        svc = ChunkingService(s3_client=MagicMock(), sqs_client=MagicMock())
        timed_words = svc.parse_timed_words(sample_transcript)

        # Act
        result = svc.build_sentences(timed_words)

        # Assert
        assert len(result) == 3
        assert result[0]["text"] == "Hello, my name is Wes."
        assert result[0]["start_time"] == 0.0
        assert result[0]["end_time"] == 1.2
        assert result[0]["word_count"] == 5
        assert result[1]["text"] == "I talk about RAG pipelines."
        assert result[2]["text"] == "They are useful."

    def test_build_sentences_no_punctuation(self):
        # Arrange
        svc = ChunkingService(s3_client=MagicMock(), sqs_client=MagicMock())
        timed_words = [
            {"text": "Hello", "start_time": 0.0, "end_time": 0.5},
            {"text": "world", "start_time": 0.6, "end_time": 1.0},
        ]

        # Act
        result = svc.build_sentences(timed_words)

        # Assert
        assert len(result) == 1
        assert result[0]["text"] == "Hello world"
        assert result[0]["word_count"] == 2


class TestChunk:
    def test_chunk_short_transcript(self, sample_transcript):
        # Arrange
        svc = ChunkingService(s3_client=MagicMock(), sqs_client=MagicMock())
        timed_words = svc.parse_timed_words(sample_transcript)

        # Act
        result = svc.chunk(timed_words, "test-video", "uploads/test.mp3", "Jane", "Talk")

        # Assert
        assert len(result) == 1
        assert result[0]["chunk_id"] == "test-video-chunk-001"
        assert result[0]["video_id"] == "test-video"
        assert result[0]["sequence"] == 1

    def test_chunk_long_transcript(self, long_transcript):
        # Arrange
        svc = ChunkingService(s3_client=MagicMock(), sqs_client=MagicMock())
        timed_words = svc.parse_timed_words(long_transcript)

        # Act
        result = svc.chunk(timed_words, "long-video", "uploads/long.mp3", None, None)

        # Assert
        assert len(result) > 1
        for chunk in result:
            assert chunk["text"]
            assert chunk["word_count"] > 0

    def test_chunk_overlap(self, long_transcript):
        # Arrange
        svc = ChunkingService(s3_client=MagicMock(), sqs_client=MagicMock())
        timed_words = svc.parse_timed_words(long_transcript)

        # Act
        result = svc.chunk(timed_words, "long-video", "uploads/long.mp3", None, None)

        # Assert
        assert len(result) >= 2
        first_words = set(result[0]["text"].split())
        second_words = set(result[1]["text"].split())
        overlap = first_words & second_words
        assert len(overlap) >= 40

    def test_chunk_metadata(self, sample_transcript):
        # Arrange
        svc = ChunkingService(s3_client=MagicMock(), sqs_client=MagicMock())
        timed_words = svc.parse_timed_words(sample_transcript)

        # Act
        result = svc.chunk(timed_words, "test-video", "uploads/test.mp3", "Jane Doe", "Building RAG")

        # Assert
        chunk = result[0]
        assert chunk["video_id"] == "test-video"
        assert chunk["sequence"] == 1
        assert chunk["start_time"] == 0.0
        assert chunk["end_time"] == 3.8
        assert chunk["metadata"]["speaker"] == "Jane Doe"
        assert chunk["metadata"]["title"] == "Building RAG"
        assert chunk["metadata"]["source_s3_key"] == "uploads/test.mp3"
        assert chunk["metadata"]["total_chunks"] == 1


class TestStoreChunks:
    def test_store_chunks_writes_to_s3(self, s3_bucket, mock_aws_services):
        # Arrange
        s3_client = mock_aws_services["s3"]
        svc = ChunkingService(s3_client=s3_client, sqs_client=MagicMock())
        chunks = [
            {"chunk_id": "vid-chunk-001", "sequence": 1, "text": "Hello."},
            {"chunk_id": "vid-chunk-002", "sequence": 2, "text": "World."},
        ]

        # Act
        svc.store_chunks(s3_bucket, "vid", chunks)

        # Assert
        obj1 = s3_client.get_object(Bucket=s3_bucket, Key="chunks/vid/chunk-001.json")
        obj2 = s3_client.get_object(Bucket=s3_bucket, Key="chunks/vid/chunk-002.json")
        assert json.loads(obj1["Body"].read())["text"] == "Hello."
        assert json.loads(obj2["Body"].read())["text"] == "World."

    def test_store_chunks_returns_keys(self, s3_bucket, mock_aws_services):
        # Arrange
        s3_client = mock_aws_services["s3"]
        svc = ChunkingService(s3_client=s3_client, sqs_client=MagicMock())
        chunks = [
            {"chunk_id": "vid-chunk-001", "sequence": 1, "text": "Hello."},
            {"chunk_id": "vid-chunk-002", "sequence": 2, "text": "World."},
        ]

        # Act
        keys = svc.store_chunks(s3_bucket, "vid", chunks)

        # Assert
        assert keys == [
            "chunks/vid/chunk-001.json",
            "chunks/vid/chunk-002.json",
        ]


class TestPublishChunks:
    def test_publish_chunks_sends_sqs_messages(self):
        # Arrange
        mock_sqs = MagicMock()
        svc = ChunkingService(s3_client=MagicMock(), sqs_client=mock_sqs)
        chunk_keys = [
            "chunks/vid/chunk-001.json",
            "chunks/vid/chunk-002.json",
            "chunks/vid/chunk-003.json",
        ]

        # Act
        svc.publish_chunks(
            "https://sqs.us-east-1.amazonaws.com/123/queue",
            chunk_keys, "test-bucket", "vid", "Jane", "Talk",
        )

        # Assert
        assert mock_sqs.send_message.call_count == 3
        first_call_body = json.loads(
            mock_sqs.send_message.call_args_list[0][1]["MessageBody"]
        )
        assert first_call_body["chunk_s3_key"] == "chunks/vid/chunk-001.json"
        assert first_call_body["bucket"] == "test-bucket"
        assert first_call_body["video_id"] == "vid"
        assert first_call_body["speaker"] == "Jane"
        assert first_call_body["title"] == "Talk"

    def test_publish_chunks_returns_count(self):
        # Arrange
        mock_sqs = MagicMock()
        svc = ChunkingService(s3_client=MagicMock(), sqs_client=mock_sqs)
        chunk_keys = [
            "chunks/vid/chunk-001.json",
            "chunks/vid/chunk-002.json",
            "chunks/vid/chunk-003.json",
        ]

        # Act
        result = svc.publish_chunks(
            "https://sqs.us-east-1.amazonaws.com/123/queue",
            chunk_keys, "test-bucket", "vid", None, None,
        )

        # Assert
        assert result == 3
