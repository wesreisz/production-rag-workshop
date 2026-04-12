import io
import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from src.handlers.embed_text import handler

TEST_API_KEY = "test-api-key-32-chars-long-here!"
FAKE_EMBEDDING = [0.01 * i for i in range(256)]


def _make_bedrock_response(vector):
    body_bytes = json.dumps({"embedding": vector}).encode()
    return {"body": io.BytesIO(body_bytes)}


def _make_event(body=None, api_key=TEST_API_KEY):
    return {
        "headers": {"x-api-key": api_key} if api_key is not None else {},
        "body": body,
    }


class TestValidRequest:
    def test_valid_request_returns_200(self, aws_credentials):
        # Arrange
        event = _make_event(body=json.dumps({"text": "What is RAG?"}))
        mock_response = _make_bedrock_response(FAKE_EMBEDDING)

        with patch("src.handlers.embed_text._bedrock") as mock_bedrock:
            mock_bedrock.invoke_model.return_value = mock_response

            # Act
            response = handler(event, None)

        # Assert
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert "embedding" in body
        assert body["embedding"] == FAKE_EMBEDDING


class TestAuthValidation:
    def test_missing_api_key_returns_401(self, aws_credentials):
        # Arrange
        event = _make_event(body=json.dumps({"text": "hello"}), api_key=None)

        # Act
        response = handler(event, None)

        # Assert
        assert response["statusCode"] == 401
        assert json.loads(response["body"]) == {"error": "unauthorized"}

    def test_wrong_api_key_returns_401(self, aws_credentials):
        # Arrange
        event = _make_event(body=json.dumps({"text": "hello"}), api_key="wrong-key")

        # Act
        response = handler(event, None)

        # Assert
        assert response["statusCode"] == 401
        assert json.loads(response["body"]) == {"error": "unauthorized"}


class TestInputValidation:
    def test_missing_text_field_returns_400(self, aws_credentials):
        # Arrange
        event = _make_event(body=json.dumps({"other_field": "value"}))

        # Act
        response = handler(event, None)

        # Assert
        assert response["statusCode"] == 400
        assert "text" in json.loads(response["body"])["error"]

    def test_empty_text_returns_400(self, aws_credentials):
        # Arrange
        event = _make_event(body=json.dumps({"text": ""}))

        # Act
        response = handler(event, None)

        # Assert
        assert response["statusCode"] == 400

    def test_malformed_json_returns_400(self, aws_credentials):
        # Arrange
        event = _make_event(body="not-valid-json")

        # Act
        response = handler(event, None)

        # Assert
        assert response["statusCode"] == 400
        assert json.loads(response["body"]) == {"error": "body must be valid JSON"}


class TestBedrockError:
    def test_bedrock_error_returns_500(self, aws_credentials):
        # Arrange
        event = _make_event(body=json.dumps({"text": "What is RAG?"}))
        client_error = ClientError(
            error_response={"Error": {"Code": "ThrottlingException", "Message": "Too many requests"}},
            operation_name="InvokeModel",
        )

        with patch("src.handlers.embed_text._bedrock") as mock_bedrock:
            mock_bedrock.invoke_model.side_effect = client_error

            # Act
            response = handler(event, None)

        # Assert
        assert response["statusCode"] == 500
        assert json.loads(response["body"]) == {"error": "internal error"}
