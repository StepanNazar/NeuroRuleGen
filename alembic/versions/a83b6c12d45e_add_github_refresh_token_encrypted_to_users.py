"""Add github_refresh_token_encrypted to users

Revision ID: a83b6c12d45e
Revises: 70fdd5c80be1
Create Date: 2026-11-17 10:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a83b6c12d45e"
down_revision: str | Sequence[str] | None = "70fdd5c80be1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("github_refresh_token_encrypted", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "github_refresh_token_encrypted")
