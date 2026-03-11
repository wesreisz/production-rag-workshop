import json
import logging
import os

import boto3
import psycopg2

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

SCHEMA_SQL = [
    "CREATE EXTENSION IF NOT EXISTS vector",

    """
    CREATE TABLE IF NOT EXISTS video_chunks (
        id SERIAL PRIMARY KEY,
        chunk_id VARCHAR(255) UNIQUE NOT NULL,
        video_id VARCHAR(255) NOT NULL,
        sequence INTEGER NOT NULL,
        text TEXT NOT NULL,
        embedding vector(256),
        speaker VARCHAR(255),
        title VARCHAR(512),
        start_time FLOAT,
        end_time FLOAT,
        source_s3_key VARCHAR(1024),
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """,

    """
    CREATE INDEX IF NOT EXISTS idx_video_chunks_embedding
    ON video_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    """,

    "CREATE INDEX IF NOT EXISTS idx_video_chunks_video_id ON video_chunks(video_id)",

    "CREATE INDEX IF NOT EXISTS idx_video_chunks_speaker ON video_chunks(speaker)",
]


def handler(event, context):
    secret_arn = os.environ["SECRET_ARN"]
    db_name = os.environ["DB_NAME"]

    secretsmanager = boto3.client("secretsmanager")
    response = secretsmanager.get_secret_value(SecretId=secret_arn)
    secret = json.loads(response["SecretString"])

    conn = psycopg2.connect(
        host=secret["host"],
        port=int(secret["port"]),
        dbname=db_name,
        user=secret["username"],
        password=secret["password"],
    )

    try:
        cursor = conn.cursor()
        for sql in SCHEMA_SQL:
            logger.info("executing: %s", sql.strip()[:80])
            cursor.execute(sql)
        conn.commit()
        cursor.close()
        logger.info("all migrations applied successfully")
        return {"statusCode": 200, "body": "migrations applied"}
    except Exception:
        conn.rollback()
        logger.exception("migration failed")
        raise
    finally:
        conn.close()
