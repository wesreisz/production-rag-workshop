from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.api_client import ApiClient
from src.config import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_mock_client(json_return: dict) -> AsyncMock:
    mock_response = MagicMock()
    mock_response.json.return_value = json_return
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.get.return_value = mock_response
    return mock_client


def _patch_httpx(mock_client: AsyncMock):
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return patch("src.api_client.httpx.AsyncClient", mock_cls), mock_cls


class TestAsk:
    @pytest.mark.asyncio
    async def test_ask_sends_correct_request(self, valid_env):
        # Arrange
        mock_client = _make_mock_client({"results": []})
        ctx, mock_cls = _patch_httpx(mock_client)

        # Act
        with ctx:
            client = ApiClient()
            await client.ask("What is RAG?", 5)

        # Assert
        mock_client.post.assert_called_once_with(
            "/ask",
            json={"question": "What is RAG?", "top_k": 5},
            headers={"x-api-key": "test-api-key-12345"},
        )

    @pytest.mark.asyncio
    async def test_ask_with_speaker_filter(self, valid_env):
        # Arrange
        mock_client = _make_mock_client({"results": []})
        ctx, _ = _patch_httpx(mock_client)

        # Act
        with ctx:
            client = ApiClient()
            await client.ask("What is RAG?", 5, speaker="Jane Doe")

        # Assert
        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs["json"]["filters"] == {"speaker": "Jane Doe"}

    @pytest.mark.asyncio
    async def test_ask_timeout_raises_runtime_error(self, valid_env):
        # Arrange
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("timeout")
        ctx, _ = _patch_httpx(mock_client)

        # Act / Assert
        with ctx:
            client = ApiClient()
            with pytest.raises(RuntimeError):
                await client.ask("What is RAG?")

    @pytest.mark.asyncio
    async def test_ask_401_raises_auth_error(self, valid_env):
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=mock_response
        )
        ctx, _ = _patch_httpx(mock_client)

        # Act / Assert
        with ctx:
            client = ApiClient()
            with pytest.raises(RuntimeError, match="Authentication"):
                await client.ask("What is RAG?")

    @pytest.mark.asyncio
    async def test_ask_network_error_raises_runtime_error(self, valid_env):
        # Arrange
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.RequestError("connection refused")
        ctx, _ = _patch_httpx(mock_client)

        # Act / Assert
        with ctx:
            client = ApiClient()
            with pytest.raises(RuntimeError, match="Network"):
                await client.ask("What is RAG?")


class TestListVideos:
    @pytest.mark.asyncio
    async def test_list_videos_sends_correct_request(self, valid_env):
        # Arrange
        mock_client = _make_mock_client({"videos": []})
        ctx, _ = _patch_httpx(mock_client)

        # Act
        with ctx:
            client = ApiClient()
            await client.list_videos()

        # Assert
        mock_client.get.assert_called_once_with(
            "/videos",
            headers={"x-api-key": "test-api-key-12345"},
        )


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_returns_status(self, valid_env):
        # Arrange
        mock_client = _make_mock_client({"status": "healthy"})
        ctx, _ = _patch_httpx(mock_client)

        # Act
        with ctx:
            client = ApiClient()
            result = await client.health()

        # Assert
        assert result == {"status": "healthy"}
