"""add MLB pitcher/bullpen/batting/split stats tables + MLB park factors

Revision ID: 009
Revises: 008
Create Date: 2026-04-06
"""
from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── MLB 투수 개인 시즌 스탯 ──────────────────────────────
    op.create_table(
        "mlb_pitcher_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("team_short", sa.String(10), nullable=False),
        sa.Column("era", sa.Float(), nullable=False),
        sa.Column("fip", sa.Float(), nullable=True),
        sa.Column("whip", sa.Float(), nullable=False),
        sa.Column("k9", sa.Float(), nullable=False),
        sa.Column("bb9", sa.Float(), nullable=True),
        sa.Column("ip", sa.Float(), nullable=False),
        sa.Column("gs", sa.Integer(), nullable=True),
        sa.Column("g", sa.Integer(), nullable=True),
        sa.Column("handedness", sa.String(2), nullable=True),
        sa.Column("recent_era", sa.Float(), nullable=True),
        sa.Column("recent_whip", sa.Float(), nullable=True),
        sa.Column("fg_id", sa.String(20), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("season", "name", "team_short", name="uq_mlb_pitcher"),
    )

    # ── MLB 팀 불펜 집계 ────────────────────────────────────
    op.create_table(
        "mlb_team_bullpen_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("team_short", sa.String(10), nullable=False),
        sa.Column("bullpen_era", sa.Float(), nullable=False),
        sa.Column("bullpen_whip", sa.Float(), nullable=False),
        sa.Column("bullpen_k9", sa.Float(), nullable=True),
        sa.Column("bullpen_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("season", "team_short", name="uq_mlb_team_bullpen"),
    )

    # ── MLB 팀 타선 집계 ────────────────────────────────────
    op.create_table(
        "mlb_team_batting_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("team_short", sa.String(10), nullable=False),
        sa.Column("ops", sa.Float(), nullable=False),
        sa.Column("wrc_plus", sa.Float(), nullable=True),
        sa.Column("k_rate", sa.Float(), nullable=False),
        sa.Column("bb_rate", sa.Float(), nullable=True),
        sa.Column("iso", sa.Float(), nullable=True),
        sa.Column("babip", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("season", "team_short", name="uq_mlb_team_batting"),
    )

    # ── MLB 팀 타선 좌/우완 스플릿 ──────────────────────────
    op.create_table(
        "mlb_team_batting_split_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("team_short", sa.String(10), nullable=False),
        sa.Column("split", sa.String(10), nullable=False),
        sa.Column("ops", sa.Float(), nullable=False),
        sa.Column("wrc_plus", sa.Float(), nullable=True),
        sa.Column("pa", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(20), nullable=False, server_default="estimated"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("season", "team_short", "split", name="uq_mlb_team_batting_split"),
    )

    # ── MLB 구장 파크팩터 업데이트 (실측값 기반) ────────────
    # 출처: Baseball Reference multi-year park factors (2022-2024)
    op.execute("""
        UPDATE teams SET park_factor =
            CASE stadium_name
                WHEN 'Coors Field'                   THEN 1.140
                WHEN 'Fenway Park'                   THEN 1.070
                WHEN 'Great American Ball Park'      THEN 1.060
                WHEN 'Chase Field'                   THEN 1.050
                WHEN 'Globe Life Field'              THEN 1.040
                WHEN 'Truist Park'                   THEN 1.030
                WHEN 'loanDepot park'                THEN 1.025
                WHEN 'Citizens Bank Park'            THEN 1.020
                WHEN 'Yankee Stadium'                THEN 1.015
                WHEN 'Angel Stadium'                 THEN 1.010
                WHEN 'Dodger Stadium'                THEN 1.005
                WHEN 'Busch Stadium'                 THEN 1.000
                WHEN 'Minute Maid Park'              THEN 0.995
                WHEN 'American Family Field'         THEN 0.990
                WHEN 'Target Field'                  THEN 0.985
                WHEN 'Progressive Field'             THEN 0.980
                WHEN 'Rogers Centre'                 THEN 0.978
                WHEN 'Kauffman Stadium'              THEN 0.975
                WHEN 'Nationals Park'                THEN 0.970
                WHEN 'Oriole Park at Camden Yards'   THEN 0.970
                WHEN 'PNC Park'                      THEN 0.965
                WHEN 'T-Mobile Park'                 THEN 0.960
                WHEN 'Citi Field'                    THEN 0.958
                WHEN 'Comerica Park'                 THEN 0.955
                WHEN 'Petco Park'                    THEN 0.950
                WHEN 'Oracle Park'                   THEN 0.945
                WHEN 'Guaranteed Rate Field'         THEN 0.945
                WHEN 'Tropicana Field'               THEN 0.940
                WHEN 'Oakland Coliseum'              THEN 0.930
                ELSE park_factor
            END
        WHERE league = 'MLB'
    """)


def downgrade() -> None:
    op.drop_table("mlb_team_batting_split_stats")
    op.drop_table("mlb_team_batting_stats")
    op.drop_table("mlb_team_bullpen_stats")
    op.drop_table("mlb_pitcher_stats")
