import json

import pytest


@pytest.fixture
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123456789012:secret:test-secret")
    monkeypatch.setenv("DB_NAME", "ragdb")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "256")


@pytest.fixture
def sample_ask_event():
    return {
        "resource": "/ask",
        "path": "/ask",
        "httpMethod": "POST",
        "headers": {"Content-Type": "application/json"},
        "queryStringParameters": None,
        "body": json.dumps({"question": "What is RAG?", "top_k": 5}),
        "isBase64Encoded": False,
    }


@pytest.fixture
def sample_video_ask_event():
    return {
        "resource": "/videos/{video_id}/ask",
        "path": "/videos/hello-my_name_is_wes/ask",
        "httpMethod": "POST",
        "headers": {"Content-Type": "application/json"},
        "pathParameters": {"video_id": "hello-my_name_is_wes"},
        "queryStringParameters": None,
        "body": json.dumps({"question": "What is this about?", "top_k": 3}),
        "isBase64Encoded": False,
    }


@pytest.fixture
def sample_health_event():
    return {
        "resource": "/health",
        "path": "/health",
        "httpMethod": "GET",
        "headers": {},
        "queryStringParameters": None,
        "body": None,
        "isBase64Encoded": False,
    }


@pytest.fixture
def sample_videos_event():
    return {
        "resource": "/videos",
        "path": "/videos",
        "httpMethod": "GET",
        "headers": {},
        "queryStringParameters": None,
        "body": None,
        "isBase64Encoded": False,
    }
