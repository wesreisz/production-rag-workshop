from unittest.mock import AsyncMock, patch

import pytest

from src.tools import ask_video_question, list_indexed_videos, search_by_speaker


SAMPLE_ASK_RESPONSE = {
    "question": "What is RAG?",
    "results": [
        {
            "chunk_id": "v1-chunk-001",
            "video_id": "v1",
            "text": "RAG stands for Retrieval-Augmented Generation",
            "similarity": 0.89,
            "speaker": "Jane Doe",
            "title": "Building RAG Systems",
            "start_time": 10.0,
            "end_time": 20.0,
            "source_s3_key": "uploads/v1.mp3",
        }
    ],
}

SAMPLE_VIDEOS_RESPONSE = {
    "videos": [
        {
            "video_id": "v1",
            "speaker": "Jane Doe",
            "title": "Building RAG Systems",
            "chunk_count": 3,
        }
    ]
}


class TestAskVideoQuestion:
    @pytest.mark.asyncio
    async def test_returns_formatted_results(self, mock_env_vars):
        # Arrange
        with patch(
            "src.tools.ApiClient.ask", new_callable=AsyncMock
        ) as mock_ask:
            mock_ask.return_value = SAMPLE_ASK_RESPONSE

            # Act
            result = await ask_video_question.fn("What is RAG?")

            # Assert
            assert "Results for" in result
            assert "0.89" in result
            assert "RAG stands for Retrieval-Augmented Generation" in result
            assert "Jane Doe" in result

    @pytest.mark.asyncio
    async def test_empty_question_raises(self, mock_env_vars):
        # Act / Assert
        with pytest.raises(ValueError, match="cannot be empty"):
            await ask_video_question.fn("")


class TestListIndexedVideos:
    @pytest.mark.asyncio
    async def test_returns_formatted_table(self, mock_env_vars):
        # Arrange
        with patch(
            "src.tools.ApiClient.list_videos", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = SAMPLE_VIDEOS_RESPONSE

            # Act
            result = await list_indexed_videos.fn()

            # Assert
            assert "Indexed Videos" in result
            assert "v1" in result
            assert "Jane Doe" in result
            assert "3" in result


class TestSearchBySpeaker:
    @pytest.mark.asyncio
    async def test_passes_speaker_filter(self, mock_env_vars):
        # Arrange
        with patch(
            "src.tools.ApiClient.ask", new_callable=AsyncMock
        ) as mock_ask:
            mock_ask.return_value = {"question": "q", "results": []}

            # Act
            await search_by_speaker.fn("Jane Doe", "q")

            # Assert
            mock_ask.assert_called_once_with("q", 5, speaker="Jane Doe")
