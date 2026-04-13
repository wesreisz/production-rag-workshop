import pytest
from pydantic import ValidationError

from src.config import Settings, get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.delenv("API_ENDPOINT", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)


class TestSettings:
    def test_valid_settings(self, monkeypatch):
        # Arrange
        monkeypatch.setenv("API_ENDPOINT", "https://test-api.example.com/prod")
        monkeypatch.setenv("API_KEY", "test-api-key-12345")

        # Act
        settings = Settings()

        # Assert
        assert settings.api_endpoint == "https://test-api.example.com/prod"
        assert settings.api_key == "test-api-key-12345"

    def test_missing_api_endpoint(self, monkeypatch):
        # Arrange
        monkeypatch.setenv("API_KEY", "test-api-key-12345")

        # Act & Assert
        with pytest.raises(ValidationError):
            Settings()

    def test_missing_api_key(self, monkeypatch):
        # Arrange
        monkeypatch.setenv("API_ENDPOINT", "https://test-api.example.com/prod")

        # Act & Assert
        with pytest.raises(ValidationError):
            Settings()

    def test_api_endpoint_too_short(self, monkeypatch):
        # Arrange
        monkeypatch.setenv("API_ENDPOINT", "http")
        monkeypatch.setenv("API_KEY", "test-api-key-12345")

        # Act & Assert
        with pytest.raises(ValidationError):
            Settings()
