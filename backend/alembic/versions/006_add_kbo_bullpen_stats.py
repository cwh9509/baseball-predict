"""add kbo team bullpen stats table

Revision ID: 006
Revises: 005
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "kbo_team_bullpen_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("team_short", sa.String(20), nullable=False),
        sa.Column("bullpen_era", sa.Float(), nullable=False),
        sa.Column("bullpen_whip", sa.Float(), nullable=False),
        sa.Column("bullpen_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("season", "team_short", name="uq_kbo_team_bullpen"),
    )


def downgrade():
    op.drop_table("kbo_team_bullpen_stats")
