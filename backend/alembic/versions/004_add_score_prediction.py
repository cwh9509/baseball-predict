"""add score prediction columns to predictions

Revision ID: 004
Revises: 003
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("predictions", sa.Column("predicted_home_score", sa.Float(), nullable=True))
    op.add_column("predictions", sa.Column("predicted_away_score", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("predictions", "predicted_away_score")
    op.drop_column("predictions", "predicted_home_score")
