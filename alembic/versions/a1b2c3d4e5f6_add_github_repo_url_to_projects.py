"""add github repository URL to projects

Revision ID: a1b2c3d4e5f6
Revises: 654caeeadcae
Create Date: 2026-11-24 11:41:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "654caeeadcae"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("github_repo_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "github_repo_url")
