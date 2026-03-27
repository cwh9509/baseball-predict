"""
GET /api/v1/team/{team_id}/stats
팀 시즌 성적, 투구, 타격, 홈/원정 분리 통계
Redis 캐시: TTL 3600초
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import cache_get, cache_set
from app.dependencies import get_db
from app.models import Game, Team

router = APIRouter()


@router.get("/{team_id}/stats")
async def get_team_stats(
    team_id: int,
    season: Optional[int] = Query(None, description="시즌 연도 (기본: 현재 연도)"),
    last_n: int = Query(10, ge=1, le=30, description="최근 N경기"),
    db: AsyncSession = Depends(get_db),
):
    if season is None:
        season = date.today().year

    cache_key = f"team:stats:{team_id}:{season}:{last_n}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    team_result = await db.execute(select(Team).where(Team.id == team_id))
    team = team_result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="팀을 찾을 수 없습니다")

    season_start = date(season, 1, 1)
    season_end = date(season, 12, 31)

    # 시즌 전체 경기 (완료된 경기)
    all_games_result = await db.execute(
        select(Game).where(
            and_(
                Game.status == "final",
                Game.game_date >= season_start,
                Game.game_date <= season_end,
                (Game.home_team_id == team_id) | (Game.away_team_id == team_id),
                Game.winner_team_id.isnot(None),
            )
        ).order_by(Game.game_date.desc())
    )
    all_games = all_games_result.scalars().all()

    wins = sum(1 for g in all_games if g.winner_team_id == team_id)
    losses = len(all_games) - wins
    win_pct = wins / len(all_games) if all_games else 0.0

    home_games = [g for g in all_games if g.home_team_id == team_id]
    away_games = [g for g in all_games if g.away_team_id == team_id]
    home_wins = sum(1 for g in home_games if g.winner_team_id == team_id)
    away_wins = sum(1 for g in away_games if g.winner_team_id == team_id)

    # 최근 N경기
    recent_n = all_games[:last_n]
    recent_wins = sum(1 for g in recent_n if g.winner_team_id == team_id)
    runs_scored = sum(
        (g.home_score if g.home_team_id == team_id else g.away_score) or 0
        for g in recent_n
    )
    runs_allowed = sum(
        (g.away_score if g.home_team_id == team_id else g.home_score) or 0
        for g in recent_n
    )

    response = {
        "team": {
            "id": team.id,
            "name": team.name,
            "short_name": team.short_name,
            "league": team.league,
        },
        "season": season,
        "season_record": {
            "wins": wins,
            "losses": losses,
            "win_pct": round(win_pct, 3),
        },
        "last_n_games": {
            "n": len(recent_n),
            "wins": recent_wins,
            "losses": len(recent_n) - recent_wins,
            "runs_scored": runs_scored,
            "runs_allowed": runs_allowed,
            "run_diff": runs_scored - runs_allowed,
        },
        "pitching": {"team_era": None, "team_whip": None},   # TODO: 통계 집계
        "batting": {"team_ops": None, "team_avg": None},      # TODO: 통계 집계
        "home_record": {
            "wins": home_wins,
            "losses": len(home_games) - home_wins,
            "win_pct": round(home_wins / len(home_games), 3) if home_games else 0.0,
        },
        "away_record": {
            "wins": away_wins,
            "losses": len(away_games) - away_wins,
            "win_pct": round(away_wins / len(away_games), 3) if away_games else 0.0,
        },
    }

    await cache_set(cache_key, response, ttl=3600)
    return response
