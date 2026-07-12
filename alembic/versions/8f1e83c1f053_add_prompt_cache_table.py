"""add prompt cache table

Revision ID: 8f1e83c1f053
Revises: 32feb0b2b4ed
Create Date: 2026-07-12 12:41:58.553596

"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f1e83c1f053"
down_revision: str | None = "32feb0b2b4ed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "prompt_cache",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("virtual_model", sa.String(), nullable=False),
        sa.Column("prompt_text", sa.String(), nullable=False),
        sa.Column("prompt_embedding", Vector(768), nullable=False),
        sa.Column("response_text", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "CREATE INDEX ON prompt_cache "
        "USING ivfflat (prompt_embedding vector_cosine_ops) WITH (lists = 10)"
    )


def downgrade() -> None:
    op.drop_table("prompt_cache")
