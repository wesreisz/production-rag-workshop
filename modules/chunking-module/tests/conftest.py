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
                    "transcript": "Hello, my name is Wes. I talk about RAG."
                }
            ],
            "items": [
                {
                    "type": "pronunciation",
                    "alternatives": [{"confidence": "0.99", "content": "Hello"}],
                    "start_time": "0.0",
                    "end_time": "0.43",
                },
                {
                    "type": "punctuation",
                    "alternatives": [{"confidence": "0.0", "content": ","}],
                },
                {
                    "type": "pronunciation",
                    "alternatives": [{"confidence": "0.98", "content": "my"}],
                    "start_time": "0.44",
                    "end_time": "0.62",
                },
                {
                    "type": "pronunciation",
                    "alternatives": [{"confidence": "0.99", "content": "name"}],
                    "start_time": "0.63",
                    "end_time": "0.89",
                },
                {
                    "type": "pronunciation",
                    "alternatives": [{"confidence": "0.99", "content": "is"}],
                    "start_time": "0.90",
                    "end_time": "1.05",
                },
                {
                    "type": "pronunciation",
                    "alternatives": [{"confidence": "0.99", "content": "Wes"}],
                    "start_time": "1.06",
                    "end_time": "1.40",
                },
                {
                    "type": "punctuation",
                    "alternatives": [{"confidence": "0.0", "content": "."}],
                },
                {
                    "type": "pronunciation",
                    "alternatives": [{"confidence": "0.97", "content": "I"}],
                    "start_time": "1.50",
                    "end_time": "1.60",
                },
                {
                    "type": "pronunciation",
                    "alternatives": [{"confidence": "0.98", "content": "talk"}],
                    "start_time": "1.61",
                    "end_time": "1.90",
                },
                {
                    "type": "pronunciation",
                    "alternatives": [{"confidence": "0.99", "content": "about"}],
                    "start_time": "1.91",
                    "end_time": "2.20",
                },
                {
                    "type": "pronunciation",
                    "alternatives": [{"confidence": "0.99", "content": "RAG"}],
                    "start_time": "2.21",
                    "end_time": "2.60",
                },
                {
                    "type": "punctuation",
                    "alternatives": [{"confidence": "0.0", "content": "."}],
                },
            ],
        },
    }


@pytest.fixture
def long_transcript():
    items = []
    time_cursor = 0.0
    sentence_words = [
        "The", "quick", "brown", "fox", "jumps", "over", "the", "lazy", "dog",
    ]

    for _ in range(120):
        for word in sentence_words:
            items.append({
                "type": "pronunciation",
                "alternatives": [{"confidence": "0.99", "content": word}],
                "start_time": str(round(time_cursor, 2)),
                "end_time": str(round(time_cursor + 0.3, 2)),
            })
            time_cursor += 0.35

        items.append({
            "type": "punctuation",
            "alternatives": [{"confidence": "0.0", "content": "."}],
        })

    full_text = " ".join(
        " ".join(sentence_words) + "." for _ in range(120)
    )

    return {
        "jobName": "production-rag-long-video",
        "status": "COMPLETED",
        "results": {
            "transcripts": [{"transcript": full_text}],
            "items": items,
        },
    }
