"""add memories table

Revision ID: b3c4d5e6f7a8
Revises: a7b8c9d0e1f2
Create Date: 2026-03-10 00:00:00.000000+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "memories",
        sa.Column(
            "memory_id",
            sa.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column(
            "collection",
            sa.String(),
            nullable=False,
            server_default="default",
        ),
        sa.Column(
            "metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.execute("ALTER TABLE memories ADD COLUMN embedding vector(1536)")

    op.create_index("idx_memories_collection", "memories", ["collection"])
    op.create_index(
        "idx_memories_content_hash",
        "memories",
        ["collection", "content_hash"],
        unique=True,
    )
    op.execute(
        "CREATE INDEX idx_memories_embedding ON memories "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX idx_memories_bm25 ON memories "
        "USING bm25 (memory_id, content) WITH (key_field = 'memory_id')"
    )


def downgrade() -> None:
    op.drop_index("idx_memories_bm25", table_name="memories")
    op.drop_index("idx_memories_embedding", table_name="memories")
    op.drop_index("idx_memories_content_hash", table_name="memories")
    op.drop_index("idx_memories_collection", table_name="memories")
    op.drop_table("memories")
