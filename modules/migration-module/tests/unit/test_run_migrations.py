import json
import os
from unittest.mock import MagicMock, patch

import pytest


def _make_secret(username="ragadmin", password="simple"):
    return {
        "username": username,
        "password": password,
        "host": "db.example.com",
        "port": 5432,
    }


def _run_handler_with_secret(secret_dict):
    os.environ["SECRET_ARN"] = "arn:aws:secretsmanager:us-east-1:123456789012:secret:test"
    os.environ["DB_NAME"] = "ragdb"

    mock_sm = MagicMock()
    mock_sm.get_secret_value.return_value = {"SecretString": json.dumps(secret_dict)}

    captured_url = {}

    def capture_engine(url, **kwargs):
        captured_url["url"] = url
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_engine.connect.return_value = mock_conn
        return mock_engine

    with patch("src.handlers.run_migrations.boto3") as mock_boto3, \
         patch("src.handlers.run_migrations.create_engine", side_effect=capture_engine), \
         patch("src.handlers.run_migrations.command"):
        mock_boto3.client.return_value = mock_sm
        from src.handlers.run_migrations import handler
        handler({}, None)

    return captured_url["url"]


class TestCredentialEncoding:
    def test_special_chars_in_password_encoded(self):
        # Arrange — password contains '@' which must be URL-encoded as '%40'
        secret = _make_secret(password="p@ssw0rd!")

        # Act
        connection_url = _run_handler_with_secret(secret)

        # Assert
        assert "%40" in connection_url
        assert "@" not in connection_url.split("@")[0].split("://")[1]

    def test_special_chars_in_username_encoded(self):
        # Arrange — username contains '@' which must be URL-encoded as '%40'
        secret = _make_secret(username="user@domain")

        # Act
        connection_url = _run_handler_with_secret(secret)

        # Assert
        assert "%40" in connection_url
