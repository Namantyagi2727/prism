"""seed mock-fast virtual model

Revision ID: 5ed93aa332ed
Revises: 8f1e83c1f053
Create Date: 2026-07-14 18:21:48.095356

"""

import uuid
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5ed93aa332ed"
down_revision: str | None = "8f1e83c1f053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO model_routes "
        "(id, virtual_model, priority, provider, real_model, timeout_ms) VALUES "
        f"('{uuid.uuid4()}', 'mock-fast', 1, 'openai', 'gpt-4o-mini', 10000)"
    )


def downgrade() -> None:
    op.execute("DELETE FROM model_routes WHERE virtual_model = 'mock-fast'")
