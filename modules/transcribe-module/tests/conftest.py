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
            "transcribe": boto3.client("transcribe", region_name="us-east-1"),
            "s3": boto3.client("s3", region_name="us-east-1"),
        }
