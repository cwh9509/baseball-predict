"""add lineup columns to games

Revision ID: 003
Revises: 002
Create Date: 2026-03-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("games", sa.Column("home_lineup_json", JSONB, nullable=True))
    op.add_column("games", sa.Column("away_lineup_json", JSONB, nullable=True))
    op.add_column("games", sa.Column("lineup_locked", sa.Boolean(), nullable=True, server_default="false"))
    op.add_column("games", sa.Column("lineup_locked_at", sa.TIMESTAMP(timezone=True), nullable=True))


def downgrade():
    op.drop_column("games", "lineup_locked_at")
    op.drop_column("games", "lineup_locked")
    op.drop_column("games", "away_lineup_json")
    op.drop_column("games", "home_lineup_json")
