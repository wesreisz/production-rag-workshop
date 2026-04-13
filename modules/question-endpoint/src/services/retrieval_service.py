import json
import os

import boto3
import psycopg2

from src.utils.logger import get_logger

logger = get_logger(__name__)

SEARCH_BASE_SQL = (
    "SELECT chunk_id, video_id, text, speaker, title,"
    " start_time, end_time, source_s3_key,"
    " 1 - (embedding <=> %s::vector) AS similarity"
    " FROM video_chunks"
)

SEARCH_ORDER_SQL = " ORDER BY embedding <=> %s::vector LIMIT %s"

LIST_VIDEOS_SQL = (
    "SELECT video_id, speaker, title, COUNT(*) AS chunk_count"
    " FROM video_chunks"
    " GROUP BY video_id, speaker, title"
    " ORDER BY video_id"
)

SEARCH_COLUMNS = [
    "chunk_id", "video_id", "text", "speaker", "title",
    "start_time", "end_time", "source_s3_key", "similarity",
]

LIST_VIDEOS_COLUMNS = ["video_id", "speaker", "title", "chunk_count"]


class RetrievalService:
    def __init__(self, bedrock_client=None, secretsmanager_client=None):
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

    def search_similar(self, embedding, top_k, similarity_threshold=0.0, speaker=None, video_id=None):
        conn = self.get_db_connection()
        cursor = conn.cursor()
        try:
            embedding_str = str(embedding)
            params = [embedding_str]
            conditions = []

            if video_id is not None:
                conditions.append("video_id = %s")
                params.append(video_id)

            if speaker is not None:
                conditions.append("speaker = %s")
                params.append(speaker)

            sql = SEARCH_BASE_SQL
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += SEARCH_ORDER_SQL

            params.append(embedding_str)
            params.append(top_k)

            cursor.execute(sql, params)
            rows = cursor.fetchall()

            results = [dict(zip(SEARCH_COLUMNS, row)) for row in rows]
            return [r for r in results if r["similarity"] >= similarity_threshold]
        except Exception:
            self._db_conn = None
            raise
        finally:
            cursor.close()

    def list_videos(self):
        conn = self.get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(LIST_VIDEOS_SQL)
            rows = cursor.fetchall()
            return [dict(zip(LIST_VIDEOS_COLUMNS, row)) for row in rows]
        except Exception:
            self._db_conn = None
            raise
        finally:
            cursor.close()
