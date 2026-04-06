"""add NPB pitcher/bullpen/batting/split stats tables

Revision ID: 011
Revises: 010
Create Date: 2026-04-06
"""
from alembic import op
import sqlalchemy as sa

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "npb_pitcher_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("team_short", sa.String(30), nullable=False),
        sa.Column("era", sa.Float(), nullable=False),
        sa.Column("whip", sa.Float(), nullable=False),
        sa.Column("k9", sa.Float(), nullable=False),
        sa.Column("ip", sa.Float(), nullable=False),
        sa.Column("gs", sa.Integer(), nullable=True),
        sa.Column("g", sa.Integer(), nullable=True),
        sa.Column("handedness", sa.String(2), nullable=True),
        sa.Column("recent_era", sa.Float(), nullable=True),
        sa.Column("recent_whip", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("season", "name", "team_short", name="uq_npb_pitcher"),
    )

    op.create_table(
        "npb_team_bullpen_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("team_short", sa.String(30), nullable=False),
        sa.Column("bullpen_era", sa.Float(), nullable=False),
        sa.Column("bullpen_whip", sa.Float(), nullable=False),
        sa.Column("bullpen_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("season", "team_short", name="uq_npb_team_bullpen"),
    )

    op.create_table(
        "npb_team_batting_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("team_short", sa.String(30), nullable=False),
        sa.Column("ops", sa.Float(), nullable=False),
        sa.Column("wrc_plus", sa.Float(), nullable=True),
        sa.Column("k_rate", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("season", "team_short", name="uq_npb_team_batting"),
    )

    op.create_table(
        "npb_team_batting_split_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("team_short", sa.String(30), nullable=False),
        sa.Column("split", sa.String(10), nullable=False),
        sa.Column("ops", sa.Float(), nullable=False),
        sa.Column("pa", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("season", "team_short", "split", name="uq_npb_team_batting_split"),
    )

    # NPB 파크팩터 업데이트 (실측 기반 추정값)
    op.execute("""
        UPDATE teams SET park_factor =
            CASE stadium_name
                WHEN '도쿄돔'                        THEN 1.040
                WHEN '반테린 돔 나고야'               THEN 1.020
                WHEN '미즈호 PayPay 돔 후쿠오카'      THEN 1.010
                WHEN '교세라 돔 오사카'               THEN 1.000
                WHEN '벨루나 돔'                      THEN 0.990
                WHEN '라쿠텐 모바일 파크 미야기'      THEN 1.010
                WHEN '한신 고시엔 구장'               THEN 0.970
                WHEN 'MAZDA Zoom-Zoom 스타디움 히로시마' THEN 0.980
                WHEN '요코하마 스타디움'              THEN 1.030
                WHEN '메이지진구 야구장'              THEN 1.050
                WHEN 'ZOZO 마린 스타디움'             THEN 0.960
                WHEN '에스콘 필드 홋카이도'           THEN 0.990
                ELSE park_factor
            END
        WHERE league = 'NPB'
    """)


def downgrade() -> None:
    op.drop_table("npb_team_batting_split_stats")
    op.drop_table("npb_team_batting_stats")
    op.drop_table("npb_team_bullpen_stats")
    op.drop_table("npb_pitcher_stats")
