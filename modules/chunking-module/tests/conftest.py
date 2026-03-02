import os
import sys
from pathlib import Path

import boto3
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


@pytest.fixture
def mock_aws_services(aws_credentials):
    with mock_aws():
        yield


@pytest.fixture
def s3_bucket(mock_aws_services):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")
    return "test-bucket"


@pytest.fixture
def sample_transcript():
    return {
        "jobName": "production-rag-test",
        "status": "COMPLETED",
        "results": {
            "transcripts": [
                {
                    "transcript": "Hello, my name is Wes. I talk about RAG."
                }
            ],
            "items": [
                {"type": "pronunciation", "alternatives": [{"confidence": "0.99", "content": "Hello"}], "start_time": "0.0", "end_time": "0.43"},
                {"type": "punctuation", "alternatives": [{"confidence": "0.0", "content": ","}]},
                {"type": "pronunciation", "alternatives": [{"confidence": "0.98", "content": "my"}], "start_time": "0.44", "end_time": "0.62"},
                {"type": "pronunciation", "alternatives": [{"confidence": "0.99", "content": "name"}], "start_time": "0.63", "end_time": "0.90"},
                {"type": "pronunciation", "alternatives": [{"confidence": "0.99", "content": "is"}], "start_time": "0.91", "end_time": "1.05"},
                {"type": "pronunciation", "alternatives": [{"confidence": "0.99", "content": "Wes"}], "start_time": "1.06", "end_time": "1.40"},
                {"type": "punctuation", "alternatives": [{"confidence": "0.0", "content": "."}]},
                {"type": "pronunciation", "alternatives": [{"confidence": "0.97", "content": "I"}], "start_time": "1.50", "end_time": "1.60"},
                {"type": "pronunciation", "alternatives": [{"confidence": "0.98", "content": "talk"}], "start_time": "1.61", "end_time": "1.90"},
                {"type": "pronunciation", "alternatives": [{"confidence": "0.99", "content": "about"}], "start_time": "1.91", "end_time": "2.20"},
                {"type": "pronunciation", "alternatives": [{"confidence": "0.99", "content": "RAG"}], "start_time": "2.21", "end_time": "2.60"},
                {"type": "punctuation", "alternatives": [{"confidence": "0.0", "content": "."}]},
            ],
        },
    }


def _make_word_item(word, start, end):
    return {
        "type": "pronunciation",
        "alternatives": [{"confidence": "0.99", "content": word}],
        "start_time": str(start),
        "end_time": str(end),
    }


def _make_punctuation_item(char):
    return {
        "type": "punctuation",
        "alternatives": [{"confidence": "0.0", "content": char}],
    }


@pytest.fixture
def long_transcript():
    items = []
    time_cursor = 0.0
    words_in_sentence = 0
    total_words = 0

    while total_words < 1100:
        word = f"word{total_words}"
        items.append(_make_word_item(word, time_cursor, time_cursor + 0.3))
        time_cursor += 0.4
        words_in_sentence += 1
        total_words += 1

        if words_in_sentence >= 10:
            items.append(_make_punctuation_item("."))
            words_in_sentence = 0

    if words_in_sentence > 0:
        items.append(_make_punctuation_item("."))

    full_text = " ".join(
        item["alternatives"][0]["content"]
        for item in items
        if item["type"] == "pronunciation"
    )

    return {
        "jobName": "production-rag-long-test",
        "status": "COMPLETED",
        "results": {
            "transcripts": [{"transcript": full_text}],
            "items": items,
        },
    }
