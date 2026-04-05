import json
import os

import pytest


@pytest.fixture
def aws_credentials():
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["SECRET_ARN"] = "arn:aws:secretsmanager:us-east-1:123456789012:secret:test-secret"
    os.environ["DB_NAME"] = "ragdb"
    os.environ["EMBEDDING_DIMENSIONS"] = "256"
    yield
    for key in [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SECURITY_TOKEN",
        "AWS_SESSION_TOKEN",
        "AWS_DEFAULT_REGION",
        "SECRET_ARN",
        "DB_NAME",
        "EMBEDDING_DIMENSIONS",
    ]:
        os.environ.pop(key, None)


@pytest.fixture
def sample_ask_event():
    return {
        "resource": "/ask",
        "path": "/ask",
        "httpMethod": "POST",
        "headers": {"Content-Type": "application/json"},
        "pathParameters": None,
        "queryStringParameters": None,
        "body": json.dumps({"question": "What is RAG?", "top_k": 3}),
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
        "body": json.dumps({"question": "What is RAG?", "top_k": 3}),
        "isBase64Encoded": False,
    }


@pytest.fixture
def sample_health_event():
    return {
        "resource": "/health",
        "path": "/health",
        "httpMethod": "GET",
        "headers": {},
        "pathParameters": None,
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
        "pathParameters": None,
        "queryStringParameters": None,
        "body": None,
        "isBase64Encoded": False,
    }


@pytest.fixture
def sample_presign_event():
    return {
        "resource": "/videos/{video_id}/presign",
        "path": "/videos/hello-my_name_is_wes/presign",
        "httpMethod": "GET",
        "headers": {},
        "pathParameters": {"video_id": "hello-my_name_is_wes"},
        "queryStringParameters": None,
        "body": None,
        "isBase64Encoded": False,
    }


@pytest.fixture
def sample_presign_with_chunk_event():
    return {
        "resource": "/videos/{video_id}/presign",
        "path": "/videos/hello-my_name_is_wes/presign",
        "httpMethod": "GET",
        "headers": {},
        "pathParameters": {"video_id": "hello-my_name_is_wes"},
        "queryStringParameters": {"chunk_id": "hello-my_name_is_wes-chunk-003"},
        "body": None,
        "isBase64Encoded": False,
    }
