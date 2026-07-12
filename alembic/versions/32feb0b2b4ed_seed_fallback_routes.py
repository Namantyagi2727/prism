"""seed fallback routes

Revision ID: 32feb0b2b4ed
Revises: 2422159d370d
Create Date: 2026-07-12 12:30:58.417633

"""

import uuid
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "32feb0b2b4ed"
down_revision: str | None = "2422159d370d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO model_routes "
        "(id, virtual_model, priority, provider, real_model, timeout_ms) VALUES "
        f"('{uuid.uuid4()}', 'fast', 2, 'openai', 'gpt-4o-mini', 10000), "
        f"('{uuid.uuid4()}', 'fast', 3, 'anthropic', "
        f"'claude-haiku-4-5-20251001', 10000)"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM model_routes "
        "WHERE virtual_model = 'fast' AND provider IN ('openai', 'anthropic')"
    )
