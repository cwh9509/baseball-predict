"""add pitcher handedness + team batting split stats

Revision ID: 007
Revises: 006
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # KboPitcherStat에 handedness 컬럼 추가
    op.add_column(
        "kbo_pitcher_stats",
        sa.Column("handedness", sa.String(2), nullable=True),
    )

    # 팀 타선 좌우 스플릿 테이블
    op.create_table(
        "kbo_team_batting_split_stats",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("season", sa.Integer, nullable=False),
        sa.Column("team_short", sa.String(20), nullable=False),
        sa.Column("split", sa.String(10), nullable=False),
        sa.Column("ops", sa.Float, nullable=False),
        sa.Column("pa", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("season", "team_short", "split", name="uq_kbo_team_batting_split"),
    )


def downgrade() -> None:
    op.drop_table("kbo_team_batting_split_stats")
    op.drop_column("kbo_pitcher_stats", "handedness")
