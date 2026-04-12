import json

from src.services.chunking_service import OVERLAP_WORDS, ChunkingService


class TestParseTimedWords:
    def test_parse_timed_words_attaches_punctuation(self, sample_transcript):
        # Arrange
        service = ChunkingService.__new__(ChunkingService)

        # Act
        result = service.parse_timed_words(sample_transcript)

        # Assert
        assert result[0]["text"] == "Hello,"
        assert result[0]["start_time"] == 0.0
        assert result[0]["end_time"] == 0.43

    def test_parse_timed_words_empty_items(self):
        # Arrange
        service = ChunkingService.__new__(ChunkingService)
        transcript = {
            "results": {
                "transcripts": [{"transcript": ""}],
                "items": [],
            }
        }

        # Act
        result = service.parse_timed_words(transcript)

        # Assert
        assert result == []


class TestBuildSentences:
    def test_build_sentences_splits_on_period(self, sample_transcript):
        # Arrange
        service = ChunkingService.__new__(ChunkingService)
        timed_words = service.parse_timed_words(sample_transcript)

        # Act
        result = service.build_sentences(timed_words)

        # Assert
        assert len(result) == 2
        assert result[0]["text"] == "Hello, my name is Wes."
        assert result[0]["start_time"] == 0.0
        assert result[0]["end_time"] == 1.40
        assert result[0]["word_count"] == 5
        assert result[1]["text"] == "I talk about RAG."
        assert result[1]["start_time"] == 1.50
        assert result[1]["end_time"] == 2.60
        assert result[1]["word_count"] == 4

    def test_build_sentences_no_punctuation(self):
        # Arrange
        service = ChunkingService.__new__(ChunkingService)
        timed_words = [
            {"text": "Hello", "start_time": 0.0, "end_time": 0.5},
            {"text": "world", "start_time": 0.6, "end_time": 1.0},
            {"text": "foo", "start_time": 1.1, "end_time": 1.5},
        ]

        # Act
        result = service.build_sentences(timed_words)

        # Assert
        assert len(result) == 1
        assert result[0]["text"] == "Hello world foo"
        assert result[0]["word_count"] == 3


class TestChunk:
    def test_chunk_short_transcript(self, sample_transcript):
        # Arrange
        service = ChunkingService.__new__(ChunkingService)
        timed_words = service.parse_timed_words(sample_transcript)

        # Act
        result = service.chunk(
            timed_words, "test-video", "uploads/test-video.mp3", "Jane Doe", "My Talk"
        )

        # Assert
        assert len(result) == 1
        assert result[0]["sequence"] == 1
        assert result[0]["chunk_id"] == "test-video-chunk-001"
        assert result[0]["start_time"] == 0.0
        assert result[0]["end_time"] == 2.60

    def test_chunk_long_transcript(self, long_transcript):
        # Arrange
        service = ChunkingService.__new__(ChunkingService)
        timed_words = service.parse_timed_words(long_transcript)

        # Act
        result = service.chunk(
            timed_words, "long-video", "uploads/long-video.mp3", None, None
        )

        # Assert
        assert len(result) > 1
        for i, chunk in enumerate(result):
            assert chunk["sequence"] == i + 1
            assert chunk["chunk_id"] == f"long-video-chunk-{i + 1:03d}"

    def test_chunk_overlap(self, long_transcript):
        # Arrange
        service = ChunkingService.__new__(ChunkingService)
        timed_words = service.parse_timed_words(long_transcript)

        # Act
        result = service.chunk(
            timed_words, "long-video", "uploads/long-video.mp3", None, None
        )

        # Assert
        first_text = result[0]["text"]
        second_text = result[1]["text"]
        first_sentences = first_text.split(". ")
        second_sentences = second_text.split(". ")
        last_sentence_of_first = first_sentences[-1].rstrip(".")
        first_sentence_of_second = second_sentences[0].rstrip(".")
        assert last_sentence_of_first == first_sentence_of_second
        overlap_start = second_text[:200]
        assert overlap_start in first_text

    def test_chunk_metadata(self, sample_transcript):
        # Arrange
        service = ChunkingService.__new__(ChunkingService)
        timed_words = service.parse_timed_words(sample_transcript)

        # Act
        result = service.chunk(
            timed_words, "test-video", "uploads/test-video.mp3", "Jane Doe", "My Talk"
        )

        # Assert
        chunk = result[0]
        assert chunk["video_id"] == "test-video"
        assert chunk["sequence"] == 1
        assert chunk["start_time"] == 0.0
        assert chunk["end_time"] == 2.60
        assert chunk["word_count"] == 9
        assert chunk["metadata"]["source_s3_key"] == "uploads/test-video.mp3"
        assert chunk["metadata"]["total_chunks"] == 1
        assert chunk["metadata"]["speaker"] == "Jane Doe"
        assert chunk["metadata"]["title"] == "My Talk"


class TestStoreChunks:
    def test_store_chunks_writes_to_s3(self, mock_aws_services, s3_bucket):
        # Arrange
        service = ChunkingService(
            s3_client=mock_aws_services["s3"],
            sqs_client=mock_aws_services["sqs"],
        )
        chunks = [
            {
                "chunk_id": "vid-chunk-001",
                "video_id": "vid",
                "sequence": 1,
                "text": "Hello world.",
                "word_count": 2,
                "start_time": 0.0,
                "end_time": 1.0,
                "metadata": {
                    "source_s3_key": "uploads/vid.mp3",
                    "total_chunks": 1,
                    "speaker": None,
                    "title": None,
                },
            }
        ]

        # Act
        service.store_chunks(s3_bucket, "vid", chunks)

        # Assert
        response = mock_aws_services["s3"].get_object(
            Bucket=s3_bucket, Key="chunks/vid/chunk-001.json"
        )
        stored = json.loads(response["Body"].read())
        assert stored["chunk_id"] == "vid-chunk-001"
        assert stored["text"] == "Hello world."

    def test_store_chunks_returns_keys(self, mock_aws_services, s3_bucket):
        # Arrange
        service = ChunkingService(
            s3_client=mock_aws_services["s3"],
            sqs_client=mock_aws_services["sqs"],
        )
        chunks = [
            {
                "chunk_id": f"vid-chunk-{i:03d}",
                "video_id": "vid",
                "sequence": i,
                "text": f"Chunk {i}.",
                "word_count": 2,
                "start_time": float(i),
                "end_time": float(i + 1),
                "metadata": {
                    "source_s3_key": "uploads/vid.mp3",
                    "total_chunks": 2,
                    "speaker": None,
                    "title": None,
                },
            }
            for i in range(1, 3)
        ]

        # Act
        result = service.store_chunks(s3_bucket, "vid", chunks)

        # Assert
        assert result == [
            "chunks/vid/chunk-001.json",
            "chunks/vid/chunk-002.json",
        ]


class TestPublishChunks:
    def test_publish_chunks_sends_sqs_messages(self, mock_aws_services):
        # Arrange
        queue = mock_aws_services["sqs"].create_queue(QueueName="test-queue")
        queue_url = queue["QueueUrl"]
        service = ChunkingService(
            s3_client=mock_aws_services["s3"],
            sqs_client=mock_aws_services["sqs"],
        )
        chunk_keys = [
            "chunks/vid/chunk-001.json",
            "chunks/vid/chunk-002.json",
            "chunks/vid/chunk-003.json",
        ]

        # Act
        service.publish_chunks(
            queue_url, chunk_keys, "test-bucket", "vid", "Jane Doe", "My Talk"
        )

        # Assert
        messages = mock_aws_services["sqs"].receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=10
        )["Messages"]
        assert len(messages) == 3
        body = json.loads(messages[0]["Body"])
        assert body["chunk_s3_key"] == "chunks/vid/chunk-001.json"
        assert body["bucket"] == "test-bucket"
        assert body["video_id"] == "vid"
        assert body["speaker"] == "Jane Doe"
        assert body["title"] == "My Talk"

    def test_publish_chunks_returns_count(self, mock_aws_services):
        # Arrange
        queue = mock_aws_services["sqs"].create_queue(QueueName="test-queue")
        queue_url = queue["QueueUrl"]
        service = ChunkingService(
            s3_client=mock_aws_services["s3"],
            sqs_client=mock_aws_services["sqs"],
        )
        chunk_keys = [
            "chunks/vid/chunk-001.json",
            "chunks/vid/chunk-002.json",
            "chunks/vid/chunk-003.json",
        ]

        # Act
        result = service.publish_chunks(
            queue_url, chunk_keys, "test-bucket", "vid", None, None
        )

        # Assert
        assert result == 3
