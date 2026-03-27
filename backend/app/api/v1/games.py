"""
GET /api/v1/games/today
오늘의 경기 목록 + 예측 요약 + 날씨 반환
Redis 캐시: TTL 300초
"""
import json
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import cache_get, cache_set
from app.dependencies import get_db
from app.models import Game, Prediction, Team, WeatherLog
from app.schemas.game import GameResponse, GamesListResponse, PredictionBrief, TeamBrief, WeatherBrief

router = APIRouter()


@router.get("/today", response_model=GamesListResponse)
async def get_games_today(
    league: str = Query(..., description="KBO 또는 MLB"),
    target_date: Optional[str] = Query(None, alias="date", description="YYYY-MM-DD (기본: 오늘)"),
    db: AsyncSession = Depends(get_db),
):
    game_date = date.fromisoformat(target_date) if target_date else date.today()
    cache_key = f"games:today:{league}:{game_date.isoformat()}"

    # 캐시 확인
    cached = await cache_get(cache_key)
    if cached:
        return cached

    # 경기 조회
    result = await db.execute(
        select(Game)
        .where(Game.game_date == game_date, Game.league == league)
        .order_by(Game.game_time.asc().nullslast())
    )
    games = result.scalars().all()

    game_responses = []
    for game in games:
        # 팀 조회
        home_team = await _get_team(db, game.home_team_id)
        away_team = await _get_team(db, game.away_team_id)
        if not home_team or not away_team:
            continue

        # 예측 요약
        pred_brief = None
        pred_result = await db.execute(
            select(Prediction)
            .where(Prediction.game_id == game.id)
            .order_by(Prediction.predicted_at.desc())
            .limit(1)
        )
        pred = pred_result.scalar_one_or_none()
        if pred:
            winner_team = await _get_team(db, pred.predicted_winner_id)
            pred_brief = PredictionBrief(
                home_win_prob=float(pred.home_win_prob),
                predicted_winner=winner_team.name if winner_team else "알 수 없음",
                confidence_tier=pred.confidence_tier,
                has_explanation=pred.llm_explanation is not None,
            )

        # 날씨 요약
        weather_brief = None
        weather_result = await db.execute(
            select(WeatherLog)
            .where(WeatherLog.game_id == game.id)
            .order_by(WeatherLog.fetched_at.desc())
            .limit(1)
        )
        weather = weather_result.scalar_one_or_none()
        if weather:
            precip = float(weather.precipitation_mm or 0)
            weather_brief = WeatherBrief(
                temperature_c=float(weather.temperature_c) if weather.temperature_c else None,
                weather_main=weather.weather_main,
                wind_speed_ms=float(weather.wind_speed_ms) if weather.wind_speed_ms else None,
                is_raining=precip > 0.5,
            )

        game_responses.append(
            GameResponse(
                id=game.id,
                game_date=game.game_date,
                game_time=str(game.game_time) if game.game_time else None,
                status=game.status,
                home_team=TeamBrief(id=home_team.id, name=home_team.name,
                                    short_name=home_team.short_name, league=home_team.league),
                away_team=TeamBrief(id=away_team.id, name=away_team.name,
                                    short_name=away_team.short_name, league=away_team.league),
                venue=game.venue,
                prediction=pred_brief,
                weather=weather_brief,
            )
        )

    response = GamesListResponse(
        date=game_date.isoformat(),
        league=league,
        games=game_responses,
    )

    # 캐시 저장 (300초)
    await cache_set(cache_key, response.model_dump(mode="json"), ttl=300)
    return response


async def _get_team(db: AsyncSession, team_id: int) -> Optional[Team]:
    result = await db.execute(select(Team).where(Team.id == team_id))
    return result.scalar_one_or_none()
