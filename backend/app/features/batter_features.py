"""
타선 피처 계산
팀 타선 OPS 평균, wRC+, 좌완 투수 상대 OPS, 삼진율
"""
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# 리그 평균 타격 지표
MLB_BATTING_AVG = {"ops": 0.728, "wrc_plus": 100, "k_rate": 0.222}
KBO_BATTING_AVG = {"ops": 0.740, "wrc_plus": 100, "k_rate": 0.200}


async def get_lineup_features(
    db: AsyncSession,
    team_id: int,
    league: str,
    season: int,
    opponent_starter_throws: Optional[str] = None,
) -> dict:
    """
    팀 타선 피처 반환
    현재는 리그 평균값 반환 + TODO 주석
    실제 구현: pybaseball batting_stats() 활용
    """
    avg = MLB_BATTING_AVG if league == "MLB" else KBO_BATTING_AVG

    # TODO: pybaseball.batting_stats(season)에서 팀 타자들의 통계 집계
    # 1. 팀 로스터에서 타자 9명 조회
    # 2. 각 타자의 OPS, wRC+, K% 조회
    # 3. 라인업 평균 계산
    # 4. 상대 투수 투구 방향(opponent_starter_throws)에 따라 vs_LHP or vs_RHP OPS 선택

    features = {
        "lineup_ops_mean": avg["ops"],
        "lineup_wrc_plus": avg["wrc_plus"],
        "lineup_k_rate": avg["k_rate"],
        "lineup_vs_lhp_ops": avg["ops"] * 0.98,   # 임시: 좌완 상대 약간 낮게
        "lineup_vs_rhp_ops": avg["ops"] * 1.02,   # 임시: 우완 상대 약간 높게
        "is_lineup_imputed": True,
    }

    # 상대 투수가 좌완이면 vs_LHP OPS를 주 타선 지표로 사용
    if opponent_starter_throws == "L":
        features["effective_ops"] = features["lineup_vs_lhp_ops"]
    else:
        features["effective_ops"] = features["lineup_ops_mean"]

    return features
