from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.api_client import ApiClient


def _make_mock_settings():
    settings = MagicMock()
    settings.api_endpoint = "https://test-api.example.com/prod"
    settings.api_key = "test-api-key-12345"
    return settings


def _make_mock_response(json_data):
    response = MagicMock()
    response.json.return_value = json_data
    response.raise_for_status = MagicMock()
    return response


class TestAsk:
    @pytest.mark.asyncio
    async def test_ask_sends_correct_request(self):
        # Arrange
        settings = _make_mock_settings()
        client = ApiClient(settings)
        expected_response = {"question": "What is RAG?", "results": []}
        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = _make_mock_response(expected_response)

        with patch("src.api_client.httpx.AsyncClient") as mock_class:
            mock_class.return_value.__aenter__.return_value = mock_http_client

            # Act
            result = await client.ask("What is RAG?", 5)

        # Assert
        assert result == expected_response
        mock_http_client.post.assert_called_once_with(
            "/ask",
            json={"question": "What is RAG?", "top_k": 5},
            headers={"x-api-key": "test-api-key-12345"},
        )

    @pytest.mark.asyncio
    async def test_ask_with_speaker_filter(self):
        # Arrange
        settings = _make_mock_settings()
        client = ApiClient(settings)
        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = _make_mock_response({"results": []})

        with patch("src.api_client.httpx.AsyncClient") as mock_class:
            mock_class.return_value.__aenter__.return_value = mock_http_client

            # Act
            await client.ask("What is RAG?", 5, speaker="Jane Doe")

        # Assert
        call_kwargs = mock_http_client.post.call_args
        assert call_kwargs[1]["json"] == {
            "question": "What is RAG?",
            "top_k": 5,
            "filters": {"speaker": "Jane Doe"},
        }

    @pytest.mark.asyncio
    async def test_ask_timeout_raises_runtime_error(self):
        # Arrange
        settings = _make_mock_settings()
        client = ApiClient(settings)
        mock_http_client = AsyncMock()
        mock_http_client.post.side_effect = httpx.TimeoutException("timeout")

        with patch("src.api_client.httpx.AsyncClient") as mock_class:
            mock_class.return_value.__aenter__.return_value = mock_http_client

            # Act & Assert
            with pytest.raises(RuntimeError, match="timed out"):
                await client.ask("What is RAG?", 5)

    @pytest.mark.asyncio
    async def test_ask_401_raises_auth_error(self):
        # Arrange
        settings = _make_mock_settings()
        client = ApiClient(settings)
        mock_http_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unauthorized", request=MagicMock(), response=mock_response,
        )
        mock_http_client.post.return_value = mock_response

        with patch("src.api_client.httpx.AsyncClient") as mock_class:
            mock_class.return_value.__aenter__.return_value = mock_http_client

            # Act & Assert
            with pytest.raises(RuntimeError, match="Authentication"):
                await client.ask("What is RAG?", 5)

    @pytest.mark.asyncio
    async def test_ask_network_error_raises_runtime_error(self):
        # Arrange
        settings = _make_mock_settings()
        client = ApiClient(settings)
        mock_http_client = AsyncMock()
        mock_http_client.post.side_effect = httpx.RequestError("connection failed")

        with patch("src.api_client.httpx.AsyncClient") as mock_class:
            mock_class.return_value.__aenter__.return_value = mock_http_client

            # Act & Assert
            with pytest.raises(RuntimeError, match="Network error"):
                await client.ask("What is RAG?", 5)


class TestListVideos:
    @pytest.mark.asyncio
    async def test_list_videos_sends_correct_request(self):
        # Arrange
        settings = _make_mock_settings()
        client = ApiClient(settings)
        expected_response = {"videos": []}
        mock_http_client = AsyncMock()
        mock_http_client.get.return_value = _make_mock_response(expected_response)

        with patch("src.api_client.httpx.AsyncClient") as mock_class:
            mock_class.return_value.__aenter__.return_value = mock_http_client

            # Act
            result = await client.list_videos()

        # Assert
        assert result == expected_response
        mock_http_client.get.assert_called_once_with(
            "/videos",
            headers={"x-api-key": "test-api-key-12345"},
        )


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_returns_status(self):
        # Arrange
        settings = _make_mock_settings()
        client = ApiClient(settings)
        expected_response = {"status": "healthy"}
        mock_http_client = AsyncMock()
        mock_http_client.get.return_value = _make_mock_response(expected_response)

        with patch("src.api_client.httpx.AsyncClient") as mock_class:
            mock_class.return_value.__aenter__.return_value = mock_http_client

            # Act
            result = await client.health()

        # Assert
        assert result == {"status": "healthy"}
