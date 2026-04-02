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
            "sqs": boto3.client("sqs", region_name="us-east-1"),
        }


@pytest.fixture
def s3_bucket(mock_aws_services):
    mock_aws_services["s3"].create_bucket(Bucket="test-bucket")
    return "test-bucket"


@pytest.fixture
def sample_transcript():
    return {
        "jobName": "production-rag-test-video",
        "status": "COMPLETED",
        "results": {
            "transcripts": [
                {
                    "transcript": "Hello, my name is Wes. I talk about RAG pipelines. They are useful."
                }
            ],
            "items": [
                {"type": "pronunciation", "alternatives": [{"confidence": "0.99", "content": "Hello"}], "start_time": "0.0", "end_time": "0.43"},
                {"type": "punctuation", "alternatives": [{"confidence": "0.0", "content": ","}]},
                {"type": "pronunciation", "alternatives": [{"confidence": "0.98", "content": "my"}], "start_time": "0.44", "end_time": "0.62"},
                {"type": "pronunciation", "alternatives": [{"confidence": "0.99", "content": "name"}], "start_time": "0.63", "end_time": "0.85"},
                {"type": "pronunciation", "alternatives": [{"confidence": "0.99", "content": "is"}], "start_time": "0.86", "end_time": "0.95"},
                {"type": "pronunciation", "alternatives": [{"confidence": "0.99", "content": "Wes"}], "start_time": "0.96", "end_time": "1.2"},
                {"type": "punctuation", "alternatives": [{"confidence": "0.0", "content": "."}]},
                {"type": "pronunciation", "alternatives": [{"confidence": "0.98", "content": "I"}], "start_time": "1.5", "end_time": "1.6"},
                {"type": "pronunciation", "alternatives": [{"confidence": "0.97", "content": "talk"}], "start_time": "1.61", "end_time": "1.9"},
                {"type": "pronunciation", "alternatives": [{"confidence": "0.99", "content": "about"}], "start_time": "1.91", "end_time": "2.1"},
                {"type": "pronunciation", "alternatives": [{"confidence": "0.99", "content": "RAG"}], "start_time": "2.11", "end_time": "2.4"},
                {"type": "pronunciation", "alternatives": [{"confidence": "0.99", "content": "pipelines"}], "start_time": "2.41", "end_time": "2.9"},
                {"type": "punctuation", "alternatives": [{"confidence": "0.0", "content": "."}]},
                {"type": "pronunciation", "alternatives": [{"confidence": "0.99", "content": "They"}], "start_time": "3.0", "end_time": "3.2"},
                {"type": "pronunciation", "alternatives": [{"confidence": "0.99", "content": "are"}], "start_time": "3.21", "end_time": "3.4"},
                {"type": "pronunciation", "alternatives": [{"confidence": "0.99", "content": "useful"}], "start_time": "3.41", "end_time": "3.8"},
                {"type": "punctuation", "alternatives": [{"confidence": "0.0", "content": "."}]},
            ],
        },
    }


@pytest.fixture
def long_transcript():
    items = []
    time_cursor = 0.0
    word_index = 0

    for sentence_num in range(25):
        for word_num in range(50):
            word_index += 1
            start = time_cursor
            end = time_cursor + 0.3
            items.append({
                "type": "pronunciation",
                "alternatives": [{"confidence": "0.99", "content": f"word{word_index}"}],
                "start_time": str(start),
                "end_time": str(end),
            })
            time_cursor = end + 0.1

        items.append({
            "type": "punctuation",
            "alternatives": [{"confidence": "0.0", "content": "."}],
        })

    return {
        "jobName": "production-rag-long-video",
        "status": "COMPLETED",
        "results": {
            "transcripts": [{"transcript": "long transcript text"}],
            "items": items,
        },
    }
