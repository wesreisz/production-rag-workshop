from unittest.mock import AsyncMock, patch

import pytest

from src.config import get_settings
from src.tools import ask_video_question, list_indexed_videos, search_by_speaker, watch_video_segment


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


SAMPLE_RESULT = {
    "text": "RAG stands for retrieval-augmented generation.",
    "similarity": 0.89,
    "speaker": "Jane Doe",
    "title": "Building RAG Systems",
    "start_time": 234.5,
    "end_time": 279.8,
}

SAMPLE_VIDEO = {
    "video_id": "hello-my_name_is_wes",
    "title": "Building RAG Systems",
    "speaker": "Jane Doe",
    "chunk_count": 3,
}


class TestAskVideoQuestion:
    @pytest.mark.asyncio
    async def test_ask_video_question_returns_formatted_results(self, valid_env):
        # Arrange
        mock_ask = AsyncMock(return_value={"results": [SAMPLE_RESULT]})

        # Act
        with patch("src.tools.ApiClient") as mock_cls:
            mock_cls.return_value.ask = mock_ask
            result = await ask_video_question.fn("What is RAG?", top_k=5)

        # Assert
        assert "What is RAG?" in result
        assert "0.89" in result
        assert "Jane Doe" in result

    @pytest.mark.asyncio
    async def test_ask_video_question_empty_question_raises(self, valid_env):
        # Arrange / Act / Assert
        with pytest.raises(ValueError, match="cannot be empty"):
            await ask_video_question.fn("")


class TestListIndexedVideos:
    @pytest.mark.asyncio
    async def test_list_indexed_videos_returns_formatted_table(self, valid_env):
        # Arrange
        mock_list = AsyncMock(return_value={"videos": [SAMPLE_VIDEO]})

        # Act
        with patch("src.tools.ApiClient") as mock_cls:
            mock_cls.return_value.list_videos = mock_list
            result = await list_indexed_videos.fn()

        # Assert
        assert "| hello-my_name_is_wes |" in result
        assert "Jane Doe" in result


class TestSearchBySpeaker:
    @pytest.mark.asyncio
    async def test_search_by_speaker_passes_speaker_filter(self, valid_env):
        # Arrange
        mock_ask = AsyncMock(return_value={"results": []})

        # Act
        with patch("src.tools.ApiClient") as mock_cls:
            mock_cls.return_value.ask = mock_ask
            await search_by_speaker.fn("Jane Doe", "What is RAG?")

        # Assert
        mock_ask.assert_called_once_with("What is RAG?", 5, speaker="Jane Doe")


SAMPLE_PRESIGN_RESPONSE = {
    "presigned_url": "https://example.s3.amazonaws.com/uploads/hello-my_name_is_wes.mp3?X-Amz-Signature=abc",
    "video_id": "hello-my_name_is_wes",
    "expires_in": 3600,
    "source_s3_key": "uploads/hello-my_name_is_wes.mp3",
    "speaker": "Wesley Reisz",
    "title": "Building RAG Systems",
}


class TestWatchVideoSegment:
    @pytest.mark.asyncio
    async def test_watch_video_segment_opens_browser(self, valid_env):
        # Arrange
        mock_presign = AsyncMock(return_value=SAMPLE_PRESIGN_RESPONSE)

        # Act
        with patch("src.tools.ApiClient") as mock_cls, \
             patch("src.tools.webbrowser.open") as mock_browser:
            mock_cls.return_value.presign = mock_presign
            await watch_video_segment.fn("hello-my_name_is_wes", 234.5)

        # Assert
        called_url = mock_browser.call_args[0][0]
        assert "#t=234.5" in called_url
        assert "https://example.s3.amazonaws.com" in called_url

    @pytest.mark.asyncio
    async def test_watch_video_segment_no_start_time(self, valid_env):
        # Arrange
        mock_presign = AsyncMock(return_value=SAMPLE_PRESIGN_RESPONSE)

        # Act
        with patch("src.tools.ApiClient") as mock_cls, \
             patch("src.tools.webbrowser.open") as mock_browser:
            mock_cls.return_value.presign = mock_presign
            await watch_video_segment.fn("hello-my_name_is_wes", 0)

        # Assert
        called_url = mock_browser.call_args[0][0]
        assert "#t=" not in called_url

    @pytest.mark.asyncio
    async def test_watch_video_segment_returns_confirmation(self, valid_env):
        # Arrange
        mock_presign = AsyncMock(return_value=SAMPLE_PRESIGN_RESPONSE)

        # Act
        with patch("src.tools.ApiClient") as mock_cls, \
             patch("src.tools.webbrowser.open"):
            mock_cls.return_value.presign = mock_presign
            result = await watch_video_segment.fn("hello-my_name_is_wes", 234.5)

        # Assert
        assert "Building RAG Systems" in result
        assert "Wesley Reisz" in result
        assert "3:54" in result

    @pytest.mark.asyncio
    async def test_watch_video_segment_empty_video_id_raises(self, valid_env):
        # Arrange / Act / Assert
        with pytest.raises(ValueError, match="Video ID cannot be empty"):
            await watch_video_segment.fn("")

    @pytest.mark.asyncio
    async def test_watch_video_segment_negative_start_time_raises(self, valid_env):
        # Arrange / Act / Assert
        with pytest.raises(ValueError, match="Start time must be non-negative"):
            await watch_video_segment.fn("hello-my_name_is_wes", -1)
