"""add kbo pitcher and team batting stats tables

Revision ID: 005
Revises: 004
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "kbo_pitcher_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("team_short", sa.String(20), nullable=False),
        sa.Column("era", sa.Float(), nullable=False),
        sa.Column("whip", sa.Float(), nullable=False),
        sa.Column("k9", sa.Float(), nullable=False),
        sa.Column("ip", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("season", "name", "team_short", name="uq_kbo_pitcher"),
    )
    op.create_table(
        "kbo_team_batting_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("team_short", sa.String(20), nullable=False),
        sa.Column("ops", sa.Float(), nullable=False),
        sa.Column("wrc_plus", sa.Float(), nullable=False),
        sa.Column("k_rate", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("season", "team_short", name="uq_kbo_team_batting"),
    )


def downgrade():
    op.drop_table("kbo_team_batting_stats")
    op.drop_table("kbo_pitcher_stats")
