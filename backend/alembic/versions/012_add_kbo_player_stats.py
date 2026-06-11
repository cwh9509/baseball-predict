"""add KBO player game/season stats tables (self-aggregated)

Revision ID: 012
Revises: 011
"""
from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kbo_player_game_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("player_name", sa.String(50), nullable=False),
        sa.Column("team_short", sa.String(20), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("is_starter", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("opponent_sp_throws", sa.String(2), nullable=True),
        sa.Column("pa", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ab", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("doubles", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("triples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hr", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bb", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("so", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hbp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sf", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ip", sa.Float(), nullable=False, server_default="0"),
        sa.Column("er", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hits_allowed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bb_allowed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("so_pitched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(20), nullable=False, server_default="naver"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.UniqueConstraint("game_id", "player_name", "role", name="uq_kbo_player_game"),
    )
    op.create_index("ix_kbo_player_game_game_id", "kbo_player_game_stats", ["game_id"])
    op.create_index("ix_kbo_player_game_season", "kbo_player_game_stats", ["season"])
    op.create_index("ix_kbo_player_game_name", "kbo_player_game_stats", ["player_name"])

    op.create_table(
        "kbo_player_season_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("team_short", sa.String(20), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("pa", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ab", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("doubles", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("triples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hr", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bb", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("so", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hbp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sf", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ops", sa.Float(), nullable=True),
        sa.Column("k_rate", sa.Float(), nullable=True),
        sa.Column("ip", sa.Float(), nullable=False, server_default="0"),
        sa.Column("er", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hits_allowed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bb_allowed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("so_pitched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("games_pitched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("era", sa.Float(), nullable=True),
        sa.Column("whip", sa.Float(), nullable=True),
        sa.Column("k9", sa.Float(), nullable=True),
        sa.Column("handedness", sa.String(2), nullable=True),
        sa.Column("recent_era", sa.Float(), nullable=True),
        sa.Column("recent_whip", sa.Float(), nullable=True),
        sa.Column("db_game_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(20), nullable=False, server_default="statiz"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.UniqueConstraint("season", "name", "team_short", "role", name="uq_kbo_player_season"),
    )
    op.create_index("ix_kbo_player_season_season", "kbo_player_season_stats", ["season"])
    op.create_index("ix_kbo_player_season_name", "kbo_player_season_stats", ["name"])


def downgrade() -> None:
    op.drop_table("kbo_player_season_stats")
    op.drop_table("kbo_player_game_stats")
