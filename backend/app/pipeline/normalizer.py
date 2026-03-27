"""
원시 데이터 → DB 저장 가능한 형태로 변환
수집기의 Raw 데이터클래스를 SQLAlchemy 모델 생성용 딕셔너리로 변환
"""
from datetime import date, time
from typing import Optional

from app.collectors.base_collector import GameRaw, GameLogRaw, PitcherStatsRaw, TeamRaw


def normalize_team(raw: TeamRaw) -> dict:
    return {
        "league": raw.league,
        "name": raw.name,
        "short_name": raw.short_name,
        "city": raw.city,
        "stadium_name": raw.stadium_name,
        "stadium_lat": raw.stadium_lat,
        "stadium_lon": raw.stadium_lon,
        "roof_type": raw.roof_type,
        "park_factor": 1.000,  # 초기값, 나중에 통계로 보정
    }


def normalize_game(
    raw: GameRaw,
    home_team_id: int,
    away_team_id: int,
    home_starter_id: Optional[int] = None,
    away_starter_id: Optional[int] = None,
    winner_team_id: Optional[int] = None,
) -> dict:
    """경기 원시 데이터 → games 테이블 딕셔너리"""
    status_map = {
        "final": "final",
        "in progress": "in_progress",
        "scheduled": "scheduled",
        "postponed": "postponed",
        "cancelled": "cancelled",
        "preview": "scheduled",
        "pre-game": "scheduled",
        "game over": "final",
        "completed early": "final",
    }
    normalized_status = status_map.get(raw.status.lower(), "scheduled")

    return {
        "league": raw.league,
        "game_date": raw.game_date,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "home_starter_id": home_starter_id,
        "away_starter_id": away_starter_id,
        "home_starter_name": getattr(raw, "home_starter_name", None),
        "away_starter_name": getattr(raw, "away_starter_name", None),
        "venue": raw.venue,
        "status": normalized_status,
        "home_score": raw.home_score,
        "away_score": raw.away_score,
        "winner_team_id": winner_team_id,
        "external_game_id": raw.external_game_id,
    }
