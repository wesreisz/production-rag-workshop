import json

import boto3
import pytest
from moto import mock_aws

from src.services.chunking_service import ChunkingService


class TestParseTimedWords:
    def test_attaches_punctuation(self, sample_transcript):
        # Arrange
        service = ChunkingService()

        # Act
        words = service.parse_timed_words(sample_transcript)

        # Assert
        assert words[0]["text"] == "Hello,"
        assert words[4]["text"] == "Wes."

    def test_empty_items(self):
        # Arrange
        service = ChunkingService()
        transcript = {"results": {"items": []}}

        # Act
        words = service.parse_timed_words(transcript)

        # Assert
        assert words == []

    def test_pronunciation_only(self):
        # Arrange
        service = ChunkingService()
        transcript = {
            "results": {
                "items": [
                    {"type": "pronunciation", "alternatives": [{"content": "Hello"}], "start_time": "0.0", "end_time": "0.5"},
                    {"type": "pronunciation", "alternatives": [{"content": "world"}], "start_time": "0.6", "end_time": "1.0"},
                ]
            }
        }

        # Act
        words = service.parse_timed_words(transcript)

        # Assert
        assert len(words) == 2
        assert words[0]["text"] == "Hello"
        assert words[0]["start_time"] == 0.0
        assert words[0]["end_time"] == 0.5
        assert words[1]["text"] == "world"
        assert words[1]["start_time"] == 0.6


class TestBuildSentences:
    def test_splits_on_period(self, sample_transcript):
        # Arrange
        service = ChunkingService()
        words = service.parse_timed_words(sample_transcript)

        # Act
        sentences = service.build_sentences(words)

        # Assert
        assert len(sentences) == 2
        assert sentences[0]["text"] == "Hello, my name is Wes."
        assert sentences[0]["word_count"] == 5
        assert sentences[0]["start_time"] == 0.0
        assert sentences[0]["end_time"] == 1.40
        assert sentences[1]["text"] == "I talk about RAG."
        assert sentences[1]["word_count"] == 4
        assert sentences[1]["start_time"] == 1.50

    def test_no_punctuation(self):
        # Arrange
        service = ChunkingService()
        words = [
            {"text": "Hello", "start_time": 0.0, "end_time": 0.5},
            {"text": "world", "start_time": 0.6, "end_time": 1.0},
        ]

        # Act
        sentences = service.build_sentences(words)

        # Assert
        assert len(sentences) == 1
        assert sentences[0]["text"] == "Hello world"
        assert sentences[0]["word_count"] == 2

    def test_empty_input(self):
        # Arrange
        service = ChunkingService()

        # Act
        sentences = service.build_sentences([])

        # Assert
        assert sentences == []


class TestChunk:
    def test_short_transcript(self, sample_transcript):
        # Arrange
        service = ChunkingService()
        words = service.parse_timed_words(sample_transcript)

        # Act
        chunks = service.chunk(words, "test-video", "uploads/test.mp3")

        # Assert
        assert len(chunks) == 1
        assert chunks[0]["chunk_id"] == "test-video-chunk-001"
        assert chunks[0]["video_id"] == "test-video"
        assert chunks[0]["sequence"] == 1
        assert chunks[0]["word_count"] == 9
        assert chunks[0]["start_time"] == 0.0
        assert chunks[0]["metadata"]["source_s3_key"] == "uploads/test.mp3"
        assert chunks[0]["metadata"]["total_chunks"] == 1

    def test_long_transcript(self, long_transcript):
        # Arrange
        service = ChunkingService()
        words = service.parse_timed_words(long_transcript)

        # Act
        chunks = service.chunk(words, "long-video", "uploads/long.mp4")

        # Assert
        assert len(chunks) >= 2
        for chunk in chunks:
            assert chunk["word_count"] <= 600
            assert chunk["text"]
            assert chunk["metadata"]["total_chunks"] == len(chunks)

    def test_overlap(self, long_transcript):
        # Arrange
        service = ChunkingService()
        words = service.parse_timed_words(long_transcript)

        # Act
        chunks = service.chunk(words, "overlap-video", "uploads/overlap.mp4")

        # Assert
        if len(chunks) >= 2:
            first_chunk_words = set(chunks[0]["text"].split()[-50:])
            second_chunk_words = set(chunks[1]["text"].split()[:50])
            overlap = first_chunk_words & second_chunk_words
            assert len(overlap) > 0

    def test_metadata(self, sample_transcript):
        # Arrange
        service = ChunkingService()
        words = service.parse_timed_words(sample_transcript)

        # Act
        chunks = service.chunk(words, "meta-video", "uploads/meta.mp3")

        # Assert
        chunk = chunks[0]
        assert "chunk_id" in chunk
        assert "video_id" in chunk
        assert "sequence" in chunk
        assert "text" in chunk
        assert "word_count" in chunk
        assert chunk["start_time"] < chunk["end_time"]
        assert chunk["metadata"]["source_s3_key"] == "uploads/meta.mp3"
        assert chunk["metadata"]["total_chunks"] == 1


class TestStoreChunks:
    def test_writes_to_s3(self, s3_bucket):
        # Arrange
        service = ChunkingService()
        chunks = [
            {"chunk_id": "v-chunk-001", "sequence": 1, "text": "first chunk"},
            {"chunk_id": "v-chunk-002", "sequence": 2, "text": "second chunk"},
        ]

        # Act
        keys = service.store_chunks(s3_bucket, "v", chunks)

        # Assert
        s3 = boto3.client("s3", region_name="us-east-1")
        for key in keys:
            obj = s3.get_object(Bucket=s3_bucket, Key=key)
            body = json.loads(obj["Body"].read())
            assert "chunk_id" in body

    def test_returns_keys(self, s3_bucket):
        # Arrange
        service = ChunkingService()
        chunks = [
            {"chunk_id": "vid-chunk-001", "sequence": 1, "text": "chunk one"},
            {"chunk_id": "vid-chunk-002", "sequence": 2, "text": "chunk two"},
        ]

        # Act
        keys = service.store_chunks(s3_bucket, "vid", chunks)

        # Assert
        assert keys == [
            "chunks/vid/chunk-001.json",
            "chunks/vid/chunk-002.json",
        ]
