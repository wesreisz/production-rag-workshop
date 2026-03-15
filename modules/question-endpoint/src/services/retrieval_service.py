import json
import os

import boto3
import psycopg2

from src.utils.logger import get_logger

logger = get_logger(__name__)

SEARCH_SQL_BASE = """SELECT chunk_id, video_id, text, speaker, title,
       start_time, end_time, source_s3_key,
       1 - (embedding <=> %s::vector) AS similarity
FROM video_chunks"""

SEARCH_SQL_ORDER = """
ORDER BY embedding <=> %s::vector
LIMIT %s"""

LIST_VIDEOS_SQL = """SELECT video_id, speaker, title, COUNT(*) AS chunk_count
FROM video_chunks
GROUP BY video_id, speaker, title
ORDER BY video_id"""


class RetrievalService:
    def __init__(self) -> None:
        self._bedrock = boto3.client("bedrock-runtime")
        self._secretsmanager = boto3.client("secretsmanager")
        self._db_conn = None
        self._dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", "256"))
        self._secret_arn = os.environ["SECRET_ARN"]
        self._db_name = os.environ["DB_NAME"]

    def get_db_connection(self):
        if self._db_conn is not None and self._db_conn.closed == 0:
            return self._db_conn

        try:
            response = self._secretsmanager.get_secret_value(SecretId=self._secret_arn)
            secret = json.loads(response["SecretString"])
            self._db_conn = psycopg2.connect(
                host=secret["host"],
                port=int(secret["port"]),
                dbname=self._db_name,
                user=secret["username"],
                password=secret["password"],
            )
            return self._db_conn
        except Exception:
            self._db_conn = None
            raise

    def generate_embedding(self, text: str) -> list[float]:
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

    def search_similar(
        self,
        embedding: list[float],
        top_k: int,
        similarity_threshold: float = 0.0,
        speaker: str = None,
        video_id: str = None,
    ) -> list[dict]:
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()

            embedding_str = "[" + ", ".join(str(v) for v in embedding) + "]"

            conditions = []
            params = [embedding_str]

            if video_id:
                conditions.append("video_id = %s")
                params.append(video_id)

            if speaker:
                conditions.append("speaker = %s")
                params.append(speaker)

            sql = SEARCH_SQL_BASE
            if conditions:
                sql += "\nWHERE " + " AND ".join(conditions)
            sql += SEARCH_SQL_ORDER

            params.append(embedding_str)
            params.append(top_k)

            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()

            results = []
            for row in rows:
                similarity = row[8]
                if similarity < similarity_threshold:
                    continue
                results.append({
                    "chunk_id": row[0],
                    "video_id": row[1],
                    "text": row[2],
                    "speaker": row[3],
                    "title": row[4],
                    "start_time": row[5],
                    "end_time": row[6],
                    "source_s3_key": row[7],
                    "similarity": similarity,
                })

            cursor.close()
            return results
        except Exception:
            self._db_conn = None
            raise

    def list_videos(self) -> list[dict]:
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            cursor.execute(LIST_VIDEOS_SQL)
            rows = cursor.fetchall()

            results = [
                {
                    "video_id": row[0],
                    "speaker": row[1],
                    "title": row[2],
                    "chunk_count": row[3],
                }
                for row in rows
            ]

            cursor.close()
            return results
        except Exception:
            self._db_conn = None
            raise
