import json

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_PROFILE", "student-07")
    monkeypatch.setenv("SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123456789012:secret:test-secret")
    monkeypatch.setenv("DB_NAME", "ragdb")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "256")


@pytest.fixture
def mock_aws_services(aws_credentials):
    with mock_aws():
        yield {
            "s3": boto3.client("s3", region_name="us-east-1"),
            "secretsmanager": boto3.client("secretsmanager", region_name="us-east-1"),
        }


@pytest.fixture
def sample_chunk():
    return {
        "chunk_id": "hello-my_name_is_wes-chunk-001",
        "video_id": "hello-my_name_is_wes",
        "sequence": 1,
        "text": "Hello, my name is Wes. I'm going to talk about RAG pipelines...",
        "word_count": 487,
        "start_time": 0.0,
        "end_time": 45.2,
        "metadata": {
            "speaker": "Jane Doe",
            "title": "Building RAG Systems",
            "source_s3_key": "uploads/hello-my_name_is_wes.mp3",
            "total_chunks": 3,
        },
    }


@pytest.fixture
def sample_sqs_event():
    return {
        "Records": [
            {
                "messageId": "a1b2c3d4-5678-90ab-cdef-111111111111",
                "receiptHandle": "test-receipt-handle",
                "body": json.dumps({
                    "chunk_s3_key": "chunks/hello-my_name_is_wes/chunk-001.json",
                    "bucket": "test-bucket",
                    "video_id": "hello-my_name_is_wes",
                    "speaker": "Jane Doe",
                    "title": "Building RAG Systems",
                }),
                "attributes": {},
                "messageAttributes": {},
                "md5OfBody": "test",
                "eventSource": "aws:sqs",
                "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:test-queue",
                "awsRegion": "us-east-1",
            }
        ]
    }


@pytest.fixture
def s3_bucket(mock_aws_services):
    mock_aws_services["s3"].create_bucket(Bucket="test-bucket")
    return "test-bucket"
