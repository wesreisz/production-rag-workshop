from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools import ask_video_question, list_indexed_videos, search_by_speaker


class TestAskVideoQuestion:
    @pytest.mark.asyncio
    async def test_ask_video_question_returns_formatted_results(self):
        # Arrange
        mock_api_response = {
            "question": "What is RAG?",
            "results": [
                {
                    "text": "Error handling in production RAG systems requires...",
                    "similarity": 0.89,
                    "speaker": "Jane Doe",
                    "title": "Building RAG",
                    "start_time": 234.5,
                    "end_time": 279.8,
                },
            ],
        }
        mock_client_instance = AsyncMock()
        mock_client_instance.ask.return_value = mock_api_response

        with patch("src.tools.get_settings", return_value=MagicMock()), \
             patch("src.tools.ApiClient", return_value=mock_client_instance):

            # Act
            result = await ask_video_question("What is RAG?", 5)

        # Assert
        assert "Results for" in result
        assert "0.89" in result
        assert "Jane Doe" in result
        assert "Building RAG" in result

    @pytest.mark.asyncio
    async def test_ask_video_question_empty_question_raises(self):
        # Act & Assert
        with pytest.raises(ValueError, match="empty"):
            await ask_video_question("", 5)


class TestListIndexedVideos:
    @pytest.mark.asyncio
    async def test_list_indexed_videos_returns_formatted_table(self):
        # Arrange
        mock_api_response = {
            "videos": [
                {
                    "video_id": "vid-1",
                    "title": "RAG Talk",
                    "speaker": "Jane",
                    "chunk_count": 3,
                },
            ],
        }
        mock_client_instance = AsyncMock()
        mock_client_instance.list_videos.return_value = mock_api_response

        with patch("src.tools.get_settings", return_value=MagicMock()), \
             patch("src.tools.ApiClient", return_value=mock_client_instance):

            # Act
            result = await list_indexed_videos()

        # Assert
        assert "Indexed Videos" in result
        assert "vid-1" in result
        assert "RAG Talk" in result
        assert "Jane" in result
        assert "3" in result


class TestSearchBySpeaker:
    @pytest.mark.asyncio
    async def test_search_by_speaker_passes_speaker_filter(self):
        # Arrange
        mock_api_response = {
            "question": "What about RAG?",
            "results": [
                {
                    "text": "Some content",
                    "similarity": 0.85,
                    "speaker": "Jane Doe",
                    "title": "RAG Talk",
                    "start_time": 10.0,
                    "end_time": 20.0,
                },
            ],
        }
        mock_client_instance = AsyncMock()
        mock_client_instance.ask.return_value = mock_api_response

        with patch("src.tools.get_settings", return_value=MagicMock()), \
             patch("src.tools.ApiClient", return_value=mock_client_instance):

            # Act
            await search_by_speaker("Jane Doe", "What about RAG?", 5)

        # Assert
        mock_client_instance.ask.assert_called_once_with(
            "What about RAG?", 5, speaker="Jane Doe",
        )
