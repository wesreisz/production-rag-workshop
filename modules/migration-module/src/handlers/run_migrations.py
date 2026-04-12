import json
import os
from urllib.parse import quote_plus

import boto3
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine


def handler(event, context):
    secret_arn = os.environ["SECRET_ARN"]
    db_name = os.environ["DB_NAME"]

    sm = boto3.client("secretsmanager")
    secret = json.loads(sm.get_secret_value(SecretId=secret_arn)["SecretString"])

    username = quote_plus(secret["username"])
    password = quote_plus(secret["password"])
    connection_url = (
        f"postgresql+psycopg2://{username}:{password}"
        f"@{secret['host']}:{secret['port']}/{db_name}"
    )

    engine = create_engine(connection_url)

    migrations_dir = os.path.join(os.path.dirname(__file__), "..", "..", "migrations")
    alembic_cfg = Config(os.path.join(migrations_dir, "alembic.ini"))
    alembic_cfg.set_main_option("script_location", migrations_dir)

    with engine.connect() as connection:
        alembic_cfg.attributes["connection"] = connection
        command.upgrade(alembic_cfg, "head")

    return {"statusCode": 200, "detail": {"message": "migrations applied"}}
