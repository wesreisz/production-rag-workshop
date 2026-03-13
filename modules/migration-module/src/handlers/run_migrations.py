import json
import logging
import os
from pathlib import Path

import boto3
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MIGRATIONS_DIR = str(Path(__file__).resolve().parent.parent.parent / "migrations")


def handler(event, context):
    secret_arn = os.environ["SECRET_ARN"]
    db_name = os.environ["DB_NAME"]

    secretsmanager = boto3.client("secretsmanager")
    response = secretsmanager.get_secret_value(SecretId=secret_arn)
    secret = json.loads(response["SecretString"])

    url = (
        f"postgresql://{secret['username']}:{secret['password']}"
        f"@{secret['host']}:{secret['port']}/{db_name}"
    )
    engine = create_engine(url)

    alembic_cfg = Config(os.path.join(MIGRATIONS_DIR, "alembic.ini"))
    alembic_cfg.set_main_option("script_location", MIGRATIONS_DIR)

    with engine.connect() as connection:
        alembic_cfg.attributes["connection"] = connection
        command.upgrade(alembic_cfg, "head")

    logger.info("alembic migrations applied successfully")
    return {"statusCode": 200, "body": "migrations applied"}
