import json
import os

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def aws_credentials():
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    yield
    for key in [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SECURITY_TOKEN",
        "AWS_SESSION_TOKEN",
        "AWS_DEFAULT_REGION",
    ]:
        os.environ.pop(key, None)


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
        "text": "Hello, my name is Wes. I'm going to talk about RAG pipelines.",
        "word_count": 12,
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
                "receiptHandle": "mock-receipt-handle",
                "body": json.dumps({
                    "chunk_s3_key": "chunks/hello-my_name_is_wes/chunk-001.json",
                    "bucket": "test-bucket",
                    "video_id": "hello-my_name_is_wes",
                    "speaker": "Jane Doe",
                    "title": "Building RAG Systems",
                }),
                "attributes": {},
                "messageAttributes": {},
                "md5OfBody": "mock-md5",
                "eventSource": "aws:sqs",
                "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:production-rag-embedding-queue",
                "awsRegion": "us-east-1",
            }
        ]
    }


@pytest.fixture
def s3_bucket(mock_aws_services, sample_chunk):
    mock_aws_services["s3"].create_bucket(Bucket="test-bucket")
    mock_aws_services["s3"].put_object(
        Bucket="test-bucket",
        Key="chunks/hello-my_name_is_wes/chunk-001.json",
        Body=json.dumps(sample_chunk),
        ContentType="application/json",
    )
    return "test-bucket"
