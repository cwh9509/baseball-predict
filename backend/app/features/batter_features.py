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


async def _get_kbo_team_batting_split(team_id: int, season: int, split: str, db: AsyncSession) -> Optional[float]:
    """KBO 팀 타선 vs LHP/RHP 스플릿 OPS 조회 ('vs_lhp' or 'vs_rhp')"""
    try:
        from sqlalchemy import select, and_
        from app.models import Team
        from app.models.kbo_stats import KboTeamBattingSplitStat

        team_result = await db.execute(select(Team).where(Team.id == team_id))
        team = team_result.scalar_one_or_none()
        if not team:
            return None

        for s in [season, season - 1]:
            row = (await db.execute(
                select(KboTeamBattingSplitStat).where(
                    and_(
                        KboTeamBattingSplitStat.team_short == team.short_name,
                        KboTeamBattingSplitStat.season == s,
                        KboTeamBattingSplitStat.split == split,
                    )
                )
            )).scalar_one_or_none()
            if row:
                return row.ops
        return None
    except Exception as e:
        logger.debug(f"KBO 타선 스플릿 OPS DB 조회 실패 (team_id={team_id}, split={split}): {e}")
        return None


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

    # 실제 좌우 스플릿 OPS 조회 (없으면 고정 보정 폴백)
    split_ops_vs_lhp: Optional[float] = None
    split_ops_vs_rhp: Optional[float] = None
    if league == "KBO":
        split_ops_vs_lhp = await _get_kbo_team_batting_split(team_id, season, "vs_lhp", db)
        split_ops_vs_rhp = await _get_kbo_team_batting_split(team_id, season, "vs_rhp", db)

    lhp_ops = split_ops_vs_lhp if split_ops_vs_lhp is not None else ops * 0.97
    rhp_ops = split_ops_vs_rhp if split_ops_vs_rhp is not None else ops * 1.02

    # 상대 투수 투구 방향에 따라 유효 OPS 결정
    if opponent_starter_throws == "L":
        effective_ops = lhp_ops
    else:
        effective_ops = rhp_ops

    return {
        "lineup_ops_mean":      ops,
        "lineup_wrc_plus":      wrc_plus,
        "lineup_k_rate":        k_rate,
        "lineup_vs_lhp_ops":    lhp_ops,
        "lineup_vs_rhp_ops":    rhp_ops,
        "effective_ops":        effective_ops,
        "is_lineup_imputed":    imputed,
    }
