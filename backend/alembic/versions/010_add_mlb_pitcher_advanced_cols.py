"""add advanced columns to mlb_pitcher_stats (venue ERA, pitch type, velocity)

Revision ID: 010
Revises: 009
Create Date: 2026-04-06
"""
from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 홈/원정 분리 ERA
    op.add_column("mlb_pitcher_stats", sa.Column("home_era",      sa.Float(), nullable=True))
    op.add_column("mlb_pitcher_stats", sa.Column("away_era",      sa.Float(), nullable=True))
    # 구종 비율 / 평균 구속
    op.add_column("mlb_pitcher_stats", sa.Column("fastball_pct",  sa.Float(), nullable=True))
    op.add_column("mlb_pitcher_stats", sa.Column("avg_velocity",  sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("mlb_pitcher_stats", "home_era")
    op.drop_column("mlb_pitcher_stats", "away_era")
    op.drop_column("mlb_pitcher_stats", "fastball_pct")
    op.drop_column("mlb_pitcher_stats", "avg_velocity")
