"""
타선 피처 계산
팀 타선 OPS 평균, wRC+, 좌완 투수 상대 OPS, 삼진율
KBO: statiz.co.kr 스크래핑 (로그인 필요)
MLB: pybaseball batting_stats()
"""
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# 리그 평균 타격 지표 (스탯 수집 실패 시 폴백)
MLB_BATTING_AVG = {"ops": 0.728, "wrc_plus": 100, "k_rate": 0.222}
KBO_BATTING_AVG = {"ops": 0.740, "wrc_plus": 100, "k_rate": 0.200}


async def _get_kbo_team_batting(team_id: int, season: int, db: AsyncSession) -> Optional[dict]:
    """KBO 팀 타선 스탯을 DB에서 조회 (로컬에서 업로드된 statiz 스탯)
    현 시즌 없으면 직전 시즌 폴백
    """
    try:
        from sqlalchemy import select, and_
        from app.models import Team
        from app.models.kbo_stats import KboTeamBattingStat

        team_result = await db.execute(select(Team).where(Team.id == team_id))
        team = team_result.scalar_one_or_none()
        if not team:
            return None

        for s in [season, season - 1]:
            row = (await db.execute(
                select(KboTeamBattingStat).where(
                    and_(KboTeamBattingStat.team_short == team.short_name, KboTeamBattingStat.season == s)
                )
            )).scalar_one_or_none()
            if row:
                return {"ops": row.ops, "wrc_plus": row.wrc_plus, "k_rate": row.k_rate}
        return None
    except Exception as e:
        logger.debug(f"KBO 타선 스탯 DB 조회 실패 (team_id={team_id}): {e}")
        return None


async def get_lineup_features(
    db: AsyncSession,
    team_id: int,
    league: str,
    season: int,
    opponent_starter_throws: Optional[str] = None,
) -> dict:
    """팀 타선 피처 반환"""
    avg = MLB_BATTING_AVG if league == "MLB" else KBO_BATTING_AVG

    real_stats = None
    if league == "KBO":
        real_stats = await _get_kbo_team_batting(team_id, season, db)

    if real_stats:
        ops      = real_stats["ops"]
        wrc_plus = real_stats["wrc_plus"]
        k_rate   = real_stats["k_rate"]
        imputed  = False
    else:
        ops      = avg["ops"]
        wrc_plus = avg["wrc_plus"]
        k_rate   = avg["k_rate"]
        imputed  = True

    # 상대 투수 투구 방향에 따라 유효 OPS 조정 (좌완 상대 약세)
    if opponent_starter_throws == "L":
        effective_ops = ops * 0.97
    else:
        effective_ops = ops

    return {
        "lineup_ops_mean":      ops,
        "lineup_wrc_plus":      wrc_plus,
        "lineup_k_rate":        k_rate,
        "lineup_vs_lhp_ops":    ops * 0.97,
        "lineup_vs_rhp_ops":    ops * 1.02,
        "effective_ops":        effective_ops,
        "is_lineup_imputed":    imputed,
    }
