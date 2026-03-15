import json
import os
import sys
from pathlib import Path

import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def aws_credentials():
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["SECRET_ARN"] = "arn:aws:secretsmanager:us-east-1:123456789012:secret:test-secret"
    os.environ["DB_NAME"] = "testdb"
    os.environ["EMBEDDING_DIMENSIONS"] = "256"


@pytest.fixture
def mock_aws_services(aws_credentials):
    with mock_aws():
        yield


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
        "body": json.dumps({"question": "What is this about?", "top_k": 5}),
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
