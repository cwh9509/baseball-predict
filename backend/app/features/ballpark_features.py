"""
구장 및 컨텍스트 피처 계산
파크 팩터, 경기 월, 낮경기 여부, 시즌 경과일수
"""
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Game, Team


async def get_ballpark_features(
    db: AsyncSession,
    game: Game,
) -> dict:
    """구장 및 컨텍스트 피처 반환"""
    team_result = await db.execute(select(Team).where(Team.id == game.home_team_id))
    home_team = team_result.scalar_one_or_none()

    park_factor = float(home_team.park_factor or 1.0) if home_team else 1.0
    game_date: date = game.game_date

    # 시즌 시작일 (MLB: 3월 말, KBO: 3월 말)
    season_start = date(game_date.year, 3, 28)
    days_since_start = max(0, (game_date - season_start).days)

    # 낮경기 여부 (14:05 이전 시작)
    is_day_game = False
    if game.game_time:
        is_day_game = game.game_time.hour < 17

    return {
        "park_factor": park_factor,
        "game_month": game_date.month,
        "is_day_game": is_day_game,
        "days_since_season_start": days_since_start,
    }
