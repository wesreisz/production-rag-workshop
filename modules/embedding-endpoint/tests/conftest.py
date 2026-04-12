import os

import pytest

os.environ.setdefault("API_KEY", "test-api-key-32-chars-long-here!")
os.environ.setdefault("EMBEDDING_DIMENSIONS", "256")


@pytest.fixture
def aws_credentials():
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["API_KEY"] = "test-api-key-32-chars-long-here!"
    os.environ["EMBEDDING_DIMENSIONS"] = "256"
    yield
    for key in [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SECURITY_TOKEN",
        "AWS_SESSION_TOKEN",
        "AWS_DEFAULT_REGION",
    ]:
        os.environ.pop(key, None)
