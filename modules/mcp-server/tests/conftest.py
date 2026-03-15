import pytest

from src.config import get_settings


@pytest.fixture
def mock_env_vars(monkeypatch):
    monkeypatch.setenv(
        "API_ENDPOINT",
        "https://test-api.execute-api.us-east-1.amazonaws.com/prod",
    )
    monkeypatch.setenv("API_KEY", "test-api-key-1234567890")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
