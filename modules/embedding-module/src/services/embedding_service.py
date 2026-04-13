import json
import os

import boto3
import psycopg2

from src.utils.logger import get_logger

logger = get_logger(__name__)

UPSERT_SQL = """
INSERT INTO video_chunks (
    chunk_id, video_id, sequence, text, embedding,
    speaker, title, start_time, end_time, source_s3_key, created_at
) VALUES (
    %s, %s, %s, %s, %s::vector,
    %s, %s, %s, %s, %s, NOW()
)
ON CONFLICT (chunk_id) DO UPDATE SET
    text = EXCLUDED.text,
    embedding = EXCLUDED.embedding,
    speaker = EXCLUDED.speaker,
    title = EXCLUDED.title,
    updated_at = NOW();
"""


class EmbeddingService:
    def __init__(self, s3_client=None, bedrock_client=None, secretsmanager_client=None):
        self._s3 = s3_client or boto3.client("s3")
        self._bedrock = bedrock_client or boto3.client("bedrock-runtime")
        self._secretsmanager = secretsmanager_client or boto3.client("secretsmanager")
        self._db_conn = None
        self._dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", "256"))
        self._secret_arn = os.environ["SECRET_ARN"]
        self._db_name = os.environ["DB_NAME"]

    def get_db_connection(self):
        if self._db_conn is not None and not self._db_conn.closed:
            return self._db_conn

        try:
            response = self._secretsmanager.get_secret_value(SecretId=self._secret_arn)
            secret = json.loads(response["SecretString"])

            self._db_conn = psycopg2.connect(
                host=secret["host"],
                port=secret["port"],
                dbname=self._db_name,
                user=secret["username"],
                password=secret["password"],
            )
            return self._db_conn
        except Exception:
            self._db_conn = None
            raise

    def read_chunk(self, bucket, key):
        response = self._s3.get_object(Bucket=bucket, Key=key)
        return json.loads(response["Body"].read())

    def generate_embedding(self, text):
        response = self._bedrock.invoke_model(
            modelId="amazon.titan-embed-text-v2:0",
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "inputText": text,
                "dimensions": self._dimensions,
                "normalize": True,
            }),
        )
        result = json.loads(response["body"].read())
        return result["embedding"]

    def store_embedding(self, chunk, embedding):
        conn = self.get_db_connection()
        cursor = conn.cursor()
        embedding_str = str(embedding)

        cursor.execute(UPSERT_SQL, (
            chunk["chunk_id"],
            chunk["video_id"],
            chunk["sequence"],
            chunk["text"],
            embedding_str,
            chunk["metadata"].get("speaker"),
            chunk["metadata"].get("title"),
            chunk["start_time"],
            chunk["end_time"],
            chunk["metadata"]["source_s3_key"],
        ))
        conn.commit()
        cursor.close()
