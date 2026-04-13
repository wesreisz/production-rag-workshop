import json
import os

import alembic.command
import boto3
from alembic.config import Config
from sqlalchemy import create_engine


def handler(event, context):
    try:
        secret_arn = os.environ["SECRET_ARN"]
        db_name = os.environ["DB_NAME"]

        client = boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId=secret_arn)
        secret = json.loads(response["SecretString"])

        host = secret["host"]
        port = secret["port"]
        username = secret["username"]
        password = secret["password"]
        dbname = secret.get("dbname", db_name)

        url = f"postgresql://{username}:{password}@{host}:{port}/{dbname}"
        engine = create_engine(url)

        with engine.connect() as connection:
            alembic_ini_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "migrations",
                "alembic.ini",
            )
            config = Config(alembic_ini_path)
            config.set_main_option("script_location", os.path.dirname(alembic_ini_path))
            config.attributes["connection"] = connection
            alembic.command.upgrade(config, "head")

        return {"statusCode": 200, "detail": {"message": "Migrations applied successfully"}}
    except Exception as e:
        return {"statusCode": 500, "detail": {"error": str(e)}}
