import json
import os

import boto3
import psycopg2

from src.utils.logger import get_logger

logger = get_logger(__name__)

SEARCH_SQL = """
SELECT chunk_id, video_id, text, speaker, title,
       start_time, end_time, source_s3_key,
       1 - (embedding <=> %s::vector) AS similarity
FROM video_chunks
ORDER BY embedding <=> %s::vector
LIMIT %s;
"""

SEARCH_SQL_VIDEO_ID = """
SELECT chunk_id, video_id, text, speaker, title,
       start_time, end_time, source_s3_key,
       1 - (embedding <=> %s::vector) AS similarity
FROM video_chunks
WHERE video_id = %s
ORDER BY embedding <=> %s::vector
LIMIT %s;
"""

SEARCH_SQL_SPEAKER = """
SELECT chunk_id, video_id, text, speaker, title,
       start_time, end_time, source_s3_key,
       1 - (embedding <=> %s::vector) AS similarity
FROM video_chunks
WHERE speaker = %s
ORDER BY embedding <=> %s::vector
LIMIT %s;
"""

SEARCH_SQL_BOTH = """
SELECT chunk_id, video_id, text, speaker, title,
       start_time, end_time, source_s3_key,
       1 - (embedding <=> %s::vector) AS similarity
FROM video_chunks
WHERE video_id = %s AND speaker = %s
ORDER BY embedding <=> %s::vector
LIMIT %s;
"""

LIST_VIDEOS_SQL = """
SELECT video_id, speaker, title, COUNT(*) AS chunk_count
FROM video_chunks
GROUP BY video_id, speaker, title
ORDER BY video_id;
"""


class RetrievalService:
    def __init__(self):
        self._bedrock = boto3.client("bedrock-runtime")
        self._secretsmanager = boto3.client("secretsmanager")
        self._db_conn = None
        self._dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", "256"))
        self._secret_arn = os.environ.get("SECRET_ARN", "")
        self._db_name = os.environ.get("DB_NAME", "")

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
            if video_id is not None and speaker is not None:
                cursor.execute(SEARCH_SQL_BOTH, (embedding_str, video_id, speaker, embedding_str, top_k))
            elif video_id is not None:
                cursor.execute(SEARCH_SQL_VIDEO_ID, (embedding_str, video_id, embedding_str, top_k))
            elif speaker is not None:
                cursor.execute(SEARCH_SQL_SPEAKER, (embedding_str, speaker, embedding_str, top_k))
            else:
                cursor.execute(SEARCH_SQL, (embedding_str, embedding_str, top_k))
            rows = cursor.fetchall()
            results = [
                {
                    "chunk_id": row[0],
                    "video_id": row[1],
                    "text": row[2],
                    "speaker": row[3],
                    "title": row[4],
                    "start_time": row[5],
                    "end_time": row[6],
                    "source_s3_key": row[7],
                    "similarity": row[8],
                }
                for row in rows
            ]
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
            return [
                {
                    "video_id": row[0],
                    "speaker": row[1],
                    "title": row[2],
                    "chunk_count": row[3],
                }
                for row in rows
            ]
        except Exception:
            self._db_conn = None
            raise
        finally:
            cursor.close()


service = RetrievalService()
