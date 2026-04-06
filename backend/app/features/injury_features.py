"""
MLB 부상자 명단(IL) 피처 계산
statsapi의 roster(rosterType='10Day'/'60Day') 기반

캐싱: Redis 4시간 TTL (IL은 매일 변경 가능)
선수 중요도 가중치: 포지션 + 경기당 평균 기여도 (Wins Above Replacement proxy)
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 포지션별 상대적 중요도 가중치
_POSITION_WEIGHT: dict[str, float] = {
    "SP": 2.0,   # 선발투수 (가장 중요)
    "CL": 1.8,   # 마무리
    "RP": 1.2,   # 불펜
    "C":  1.5,   # 포수
    "1B": 1.0,
    "2B": 1.1,
    "3B": 1.1,
    "SS": 1.3,   # 유격수
    "OF": 1.0,
    "DH": 0.9,
}

# MLB StatsAPI team_id 매핑 (short_name → mlbam_id)
_MLB_TEAM_IDS: dict[str, int] = {
    "ARI": 109, "ATL": 144, "BAL": 110, "BOS": 111, "CHC": 112,
    "CWS": 145, "CIN": 113, "CLE": 114, "COL": 115, "DET": 116,
    "HOU": 117, "KC": 118, "LAA": 108, "LAD": 119, "MIA": 146,
    "MIL": 158, "MIN": 142, "NYM": 121, "NYY": 147, "OAK": 133,
    "PHI": 143, "PIT": 134, "SD": 135, "SF": 137, "SEA": 136,
    "STL": 138, "TB": 139, "TEX": 140, "TOR": 141, "WSH": 120,
}


def _get_il_roster_sync(mlbam_id: int) -> list[dict]:
    """statsapi로 팀 10-day + 60-day IL 로스터 조회"""
    import statsapi

    players = []
    for roster_type in ("10Day", "60Day"):
        try:
            data = statsapi.get("roster", {
                "teamId": mlbam_id,
                "rosterType": roster_type,
            })
            for p in data.get("roster", []):
                person = p.get("person", {})
                position = p.get("position", {}).get("abbreviation", "OF")
                players.append({
                    "name": person.get("fullName", ""),
                    "position": position,
                    "roster_type": roster_type,
                })
        except Exception as e:
            logger.debug(f"IL 로스터 조회 실패 (team={mlbam_id}, type={roster_type}): {e}")
    return players


def _calc_il_impact(players: list[dict]) -> dict:
    """IL 선수 목록에서 팀 영향도 지표 계산

    Returns:
        il_count: 전체 IL 선수 수 (중복 제거)
        il_impact_score: 포지션 가중치 합산 (높을수록 팀 타격 큼)
        has_sp_on_il: 선발투수 IL 여부
        has_cl_on_il: 마무리 IL 여부
    """
    seen = set()
    unique = []
    for p in players:
        key = p["name"]
        if key not in seen:
            seen.add(key)
            unique.append(p)

    impact = sum(_POSITION_WEIGHT.get(p["position"], 1.0) for p in unique)
    has_sp = any(p["position"] == "SP" for p in unique)
    has_cl = any(p["position"] == "CL" for p in unique)

    return {
        "il_count": len(unique),
        "il_impact_score": round(impact, 2),
        "has_sp_on_il": has_sp,
        "has_cl_on_il": has_cl,
    }


async def get_team_il_features(team_short: str) -> dict:
    """팀 IL 피처 반환 (Redis 4시간 캐시)

    Returns:
        il_count, il_impact_score, has_sp_on_il, has_cl_on_il
        조회 실패 시 기본값 반환
    """
    _DEFAULT = {"il_count": 0, "il_impact_score": 0.0, "has_sp_on_il": False, "has_cl_on_il": False}

    mlbam_id = _MLB_TEAM_IDS.get(team_short)
    if mlbam_id is None:
        return _DEFAULT

    # Redis 캐시 확인
    cache_key = f"il:{team_short}"
    try:
        from app.core.redis_client import cache_get, cache_set
        cached = await cache_get(cache_key)
        if cached:
            return cached
    except Exception:
        pass

    # statsapi 조회 (동기 → 스레드)
    import asyncio
    try:
        players = await asyncio.to_thread(_get_il_roster_sync, mlbam_id)
        result = _calc_il_impact(players)
    except Exception as e:
        logger.warning(f"IL 피처 계산 실패 ({team_short}): {e}")
        return _DEFAULT

    # Redis 4시간 캐시
    try:
        await cache_set(cache_key, result, ttl=14400)
    except Exception:
        pass

    return result
