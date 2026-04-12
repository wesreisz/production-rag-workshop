import json
from unittest.mock import patch

import pytest

from src.handlers.question import handler


class TestMalformedJsonBody:
    def test_post_ask_malformed_json_returns_400(self, aws_credentials):
        # Arrange
        event = {
            "resource": "/ask",
            "httpMethod": "POST",
            "headers": {"Content-Type": "application/json"},
            "pathParameters": None,
            "queryStringParameters": None,
            "body": "not-json",
            "isBase64Encoded": False,
        }

        # Act
        response = handler(event, None)

        # Assert
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "JSON" in body["error"]

    def test_post_video_ask_malformed_json_returns_400(self, aws_credentials):
        # Arrange
        event = {
            "resource": "/videos/{video_id}/ask",
            "httpMethod": "POST",
            "headers": {"Content-Type": "application/json"},
            "pathParameters": {"video_id": "hello-my_name_is_wes"},
            "queryStringParameters": None,
            "body": "not-json",
            "isBase64Encoded": False,
        }

        # Act
        response = handler(event, None)

        # Assert
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "JSON" in body["error"]
