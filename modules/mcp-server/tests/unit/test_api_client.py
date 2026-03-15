import httpx
import pytest
import respx

from src.api_client import ApiClient
from src.config import Settings

BASE_URL = "https://test-api.execute-api.us-east-1.amazonaws.com/prod"


@pytest.fixture
def settings(mock_env_vars):
    return Settings()


@pytest.fixture
def client(settings):
    return ApiClient(settings)


class TestApiClientAsk:
    @pytest.mark.asyncio
    @respx.mock
    async def test_ask_sends_correct_request(self, client):
        # Arrange
        route = respx.post(f"{BASE_URL}/ask").mock(
            return_value=httpx.Response(200, json={"question": "q", "results": []})
        )

        # Act
        result = await client.ask("q", 5)

        # Assert
        assert route.called
        request = route.calls[0].request
        assert b'"question": "q"' in request.content or b'"question":"q"' in request.content
        assert request.headers["x-api-key"] == "test-api-key-1234567890"
        assert result == {"question": "q", "results": []}

    @pytest.mark.asyncio
    @respx.mock
    async def test_ask_with_speaker_filter(self, client):
        # Arrange
        route = respx.post(f"{BASE_URL}/ask").mock(
            return_value=httpx.Response(200, json={"question": "q", "results": []})
        )

        # Act
        await client.ask("q", 5, speaker="Jane Doe")

        # Assert
        import json
        body = json.loads(route.calls[0].request.content)
        assert body["filters"] == {"speaker": "Jane Doe"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_ask_timeout_raises_runtime_error(self, client):
        # Arrange
        respx.post(f"{BASE_URL}/ask").mock(side_effect=httpx.ConnectTimeout("timeout"))

        # Act / Assert
        with pytest.raises(RuntimeError, match="timed out"):
            await client.ask("q", 5)

    @pytest.mark.asyncio
    @respx.mock
    async def test_ask_401_raises_auth_error(self, client):
        # Arrange
        respx.post(f"{BASE_URL}/ask").mock(
            return_value=httpx.Response(401, json={"message": "Forbidden"})
        )

        # Act / Assert
        with pytest.raises(RuntimeError, match="Authentication failed"):
            await client.ask("q", 5)

    @pytest.mark.asyncio
    @respx.mock
    async def test_ask_network_error_raises_runtime_error(self, client):
        # Arrange
        respx.post(f"{BASE_URL}/ask").mock(
            side_effect=httpx.ConnectError("connection refused")
        )

        # Act / Assert
        with pytest.raises(RuntimeError, match="Network error"):
            await client.ask("q", 5)


class TestApiClientListVideos:
    @pytest.mark.asyncio
    @respx.mock
    async def test_list_videos_sends_correct_request(self, client):
        # Arrange
        route = respx.get(f"{BASE_URL}/videos").mock(
            return_value=httpx.Response(200, json={"videos": []})
        )

        # Act
        result = await client.list_videos()

        # Assert
        assert route.called
        assert route.calls[0].request.headers["x-api-key"] == "test-api-key-1234567890"
        assert result == {"videos": []}


class TestApiClientHealth:
    @pytest.mark.asyncio
    @respx.mock
    async def test_health_returns_status(self, client):
        # Arrange
        respx.get(f"{BASE_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "healthy"})
        )

        # Act
        result = await client.health()

        # Assert
        assert result == {"status": "healthy"}
