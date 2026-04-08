"""
원시 데이터 → DB 저장 가능한 형태로 변환
수집기의 Raw 데이터클래스를 SQLAlchemy 모델 생성용 딕셔너리로 변환
"""
from datetime import date, datetime, time, timezone as dt_timezone
from typing import Optional

from dateutil import tz

from app.collectors.base_collector import GameRaw, GameLogRaw, PitcherStatsRaw, TeamRaw

_UTC = tz.UTC
_KST = tz.gettz("Asia/Seoul")
# TIME WITH TIME ZONE 컬럼에 naive time을 넣으면 asyncpg 에러 발생
# 현지 시각을 UTC offset=0으로 표기해서 저장 (표시용 시각이므로 offset 무관)
_STORE_TZ = dt_timezone.utc


def _parse_game_time(game_time_local: Optional[str], league: str) -> Optional[time]:
    """game_time_local 문자열을 KST 기준 time 객체로 변환.
    MLB: UTC ISO datetime → KST(한국) 시각
    KBO/NPB: HH:MM 형식 그대로 사용 (이미 KST)
    반환값은 timezone-aware (UTC offset=0으로 표기)
    """
    if not game_time_local:
        return None
    try:
        if "T" in game_time_local:
            # MLB: statsapi에서 UTC datetime 문자열 "YYYY-MM-DDTHH:MM" 형식
            dt_str = game_time_local.rstrip("Z")
            dt_utc = datetime.fromisoformat(dt_str).replace(tzinfo=_UTC)
            dt_kst = dt_utc.astimezone(_KST)
            t = dt_kst.time()
            return t.replace(tzinfo=_STORE_TZ)
        else:
            # KBO/NPB: "HH:MM" 또는 "HH:MM:SS" 현지 시각 (KST)
            parts = game_time_local.split(":")
            return time(int(parts[0]), int(parts[1]), tzinfo=_STORE_TZ)
    except Exception:
        return None


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
        "game_time": _parse_game_time(getattr(raw, "game_time_local", None), raw.league),
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
