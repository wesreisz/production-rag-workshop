import pytest
from pydantic import ValidationError

from src.config import Settings, get_settings


class TestSettings:
    def test_valid_settings(self, mock_env_vars):
        # Arrange / Act
        settings = Settings()

        # Assert
        assert settings.api_endpoint == "https://test-api.execute-api.us-east-1.amazonaws.com/prod"
        assert settings.api_key == "test-api-key-1234567890"

    def test_missing_api_endpoint(self, monkeypatch):
        # Arrange
        monkeypatch.setenv("API_KEY", "test-api-key-1234567890")
        monkeypatch.delenv("API_ENDPOINT", raising=False)
        get_settings.cache_clear()

        # Act / Assert
        with pytest.raises(ValidationError):
            Settings()

        get_settings.cache_clear()

    def test_missing_api_key(self, monkeypatch):
        # Arrange
        monkeypatch.setenv(
            "API_ENDPOINT",
            "https://test-api.execute-api.us-east-1.amazonaws.com/prod",
        )
        monkeypatch.delenv("API_KEY", raising=False)
        get_settings.cache_clear()

        # Act / Assert
        with pytest.raises(ValidationError):
            Settings()

        get_settings.cache_clear()

    def test_api_endpoint_must_start_with_http(self, monkeypatch):
        # Arrange
        monkeypatch.setenv("API_ENDPOINT", "ftp://something.example.com/path")
        monkeypatch.setenv("API_KEY", "test-api-key-1234567890")
        get_settings.cache_clear()

        # Act / Assert
        with pytest.raises(ValidationError):
            Settings()

        get_settings.cache_clear()
