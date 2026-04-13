"""pgvector extension and video_chunks table

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


class Vector(sa.types.UserDefinedType):
    cache_ok = True

    def get_col_spec(self):
        return "vector(256)"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "video_chunks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("chunk_id", sa.String(255), unique=True, nullable=False),
        sa.Column("video_id", sa.String(255), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("embedding", Vector()),
        sa.Column("speaker", sa.String(255)),
        sa.Column("title", sa.String(512)),
        sa.Column("start_time", sa.Float),
        sa.Column("end_time", sa.Float),
        sa.Column("source_s3_key", sa.String(1024)),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime, server_default=sa.text("NOW()")),
    )

    op.execute(
        "CREATE INDEX idx_video_chunks_embedding "
        "ON video_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    op.create_index("idx_video_chunks_video_id", "video_chunks", ["video_id"])
    op.create_index("idx_video_chunks_speaker", "video_chunks", ["speaker"])


def downgrade() -> None:
    op.drop_index("idx_video_chunks_speaker")
    op.drop_index("idx_video_chunks_video_id")
    op.drop_index("idx_video_chunks_embedding")
    op.drop_table("video_chunks")
    op.execute("DROP EXTENSION IF EXISTS vector")
