"""Add starter name columns to games

Revision ID: 002
Revises: 001
Create Date: 2026-03-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("games", sa.Column("home_starter_name", sa.String(50), nullable=True))
    op.add_column("games", sa.Column("away_starter_name", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("games", "away_starter_name")
    op.drop_column("games", "home_starter_name")
