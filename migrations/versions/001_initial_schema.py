"""Initial schema: pgvector extension, video_chunks table, indexes

Revision ID: 001
Revises:
Create Date: 2026-03-09
"""
from typing import Sequence, Union

from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute("""
        CREATE TABLE video_chunks (
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
    """)

    op.execute("""
        CREATE INDEX idx_video_chunks_embedding
        ON video_chunks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    op.execute(
        "CREATE INDEX idx_video_chunks_video_id ON video_chunks(video_id)"
    )
    op.execute(
        "CREATE INDEX idx_video_chunks_speaker ON video_chunks(speaker)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_video_chunks_speaker")
    op.execute("DROP INDEX IF EXISTS idx_video_chunks_video_id")
    op.execute("DROP INDEX IF EXISTS idx_video_chunks_embedding")
    op.execute("DROP TABLE IF EXISTS video_chunks")
    op.execute("DROP EXTENSION IF EXISTS vector")
