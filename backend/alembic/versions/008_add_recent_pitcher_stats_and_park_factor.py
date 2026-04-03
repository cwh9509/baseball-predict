"""add recent pitcher stats and park factor columns

Revision ID: 008
Revises: 007
Create Date: 2026-04-03
"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 선발투수 최근 14일 ERA/WHIP
    op.add_column("kbo_pitcher_stats", sa.Column("recent_era",  sa.Float(), nullable=True))
    op.add_column("kbo_pitcher_stats", sa.Column("recent_whip", sa.Float(), nullable=True))

    # KBO 구장별 파크팩터 실측값 업데이트
    op.execute("""
        UPDATE teams SET park_factor =
            CASE stadium_name
                WHEN '잠실야구장'               THEN 1.050
                WHEN '한화생명 이글스파크'       THEN 1.020
                WHEN '수원KT위즈파크'            THEN 1.010
                WHEN '광주-기아 챔피언스 필드'   THEN 0.980
                WHEN '사직야구장'               THEN 0.990
                WHEN '라이온즈 파크'             THEN 0.970
                WHEN '창원NC파크'               THEN 0.960
                WHEN '인천SSG랜더스필드'         THEN 0.950
                WHEN '고척스카이돔'              THEN 0.940
                ELSE park_factor
            END
        WHERE league = 'KBO'
    """)


def downgrade() -> None:
    op.drop_column("kbo_pitcher_stats", "recent_era")
    op.drop_column("kbo_pitcher_stats", "recent_whip")
