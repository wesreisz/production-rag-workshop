import pytest


@pytest.fixture
def valid_env(monkeypatch):
    monkeypatch.setenv("API_ENDPOINT", "https://example.execute-api.us-east-1.amazonaws.com/prod")
    monkeypatch.setenv("API_KEY", "test-api-key-12345")
