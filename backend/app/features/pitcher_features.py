"""
선발투수 피처 계산
시즌 ERA/WHIP/K9, 최근 3선발 ERA, 휴식일수
"""
import logging
from datetime import date
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Player
from app.models.kbo_stats import KboPitcherStat

logger = logging.getLogger(__name__)

# 리그 평균값 (데이터 없을 때 사용)
MLB_LEAGUE_AVG = {"era": 4.30, "whip": 1.28, "k9": 8.7}
KBO_LEAGUE_AVG = {"era": 4.50, "whip": 1.35, "k9": 7.5}
NPB_LEAGUE_AVG = {"era": 3.80, "whip": 1.25, "k9": 8.2}


async def get_kbo_starter_era(
    name: Optional[str],
    team_short: str,
    season: int,
    db: Optional[AsyncSession] = None,
) -> Optional[float]:
    """KBO 선발투수 개인 ERA — DB에서 조회 (로컬 업로드된 statiz 스탯)
    이름 미지정 또는 데이터 없으면 None 반환 → 팀 로테이션 ERA 폴백
    현 시즌 데이터 없으면 직전 시즌으로 폴백
    """
    if not name:
        return None
    if db is not None:
        from app.models.kbo_stats import KboPitcherStat
        for s in [season, season - 1]:
            # 이름+팀 일치 우선, 이름만 일치 차선
            for extra_cond in [
                and_(KboPitcherStat.name == name, KboPitcherStat.team_short == team_short, KboPitcherStat.season == s),
                and_(KboPitcherStat.name == name, KboPitcherStat.season == s),
            ]:
                row = (await db.execute(select(KboPitcherStat).where(extra_cond))).scalar_one_or_none()
                if row:
                    return row.era
    return None


async def get_team_rotation_era(team_short: str, league: str, season: int, db: Optional[AsyncSession] = None) -> Optional[float]:
    """팀 로테이션 ERA (KBO/NPB 전용 — 개별 선발 정보 없을 때 사용)
    KBO: DB에서 팀 투수들 IP 가중 평균 ERA
    현 시즌 데이터 없으면 직전 시즌으로 폴백
    """
    if league == "KBO" and db is not None:
        from app.models.kbo_stats import KboPitcherStat
        for s in [season, season - 1]:
            rows = (await db.execute(
                select(KboPitcherStat).where(
                    and_(KboPitcherStat.team_short == team_short, KboPitcherStat.season == s)
                )
            )).scalars().all()
            if rows:
                total_ip = sum(r.ip for r in rows)
                if total_ip > 0:
                    return sum(r.era * r.ip for r in rows) / total_ip
                return sum(r.era for r in rows) / len(rows)
        return None
    if league == "NPB":
        from app.collectors.npb_collector import NPBCollector
        collector = NPBCollector()
        era = await collector.fetch_team_rotation_era(team_short, season)
        if era is None:
            era = await collector.fetch_team_rotation_era(team_short, season - 1)
        return era
    return None


async def get_pitcher_features(
    db: AsyncSession,
    pitcher_id: Optional[int],
    league: str,
    game_date: date,
    season: int,
) -> dict:
    """
    선발투수 피처 반환
    pitcher_id가 None이거나 통계가 없으면 리그 평균값 + is_imputed=True
    """
    if league == "MLB":
        avg = MLB_LEAGUE_AVG
    elif league == "NPB":
        avg = NPB_LEAGUE_AVG
    else:
        avg = KBO_LEAGUE_AVG

    if pitcher_id is None:
        return _imputed_pitcher_features(avg)

    # DB에서 선수 조회
    result = await db.execute(select(Player).where(Player.id == pitcher_id))
    pitcher = result.scalar_one_or_none()
    if not pitcher:
        return _imputed_pitcher_features(avg)

    # pybaseball에서 시즌 통계 가져오기 (비동기)
    from app.collectors.pybaseball_collector import PybaseballCollector
    collector = PybaseballCollector()
    stats = await collector.fetch_pitcher_stats(
        external_id=str(pitcher.external_id),
        season=season,
    )

    if stats is None or stats.ip < 5:
        # 5이닝 미만 → 신뢰도 낮음, 리그 평균 대체
        return _imputed_pitcher_features(avg)

    features = {
        "era_season": stats.era,
        "whip_season": stats.whip,
        "k9_season": stats.k9,
        "ip_season": stats.ip,
        "is_imputed_pitcher": False,
        "is_ace": False,  # 나중에 builder.py에서 상위 25% 여부로 업데이트
    }

    # 마지막 등판일로 휴식일수 계산
    if stats.last_appearance_date:
        features["days_rest"] = (game_date - stats.last_appearance_date).days
        features["is_fatigued"] = features["days_rest"] < 4
    else:
        features["days_rest"] = float("nan")
        features["is_fatigued"] = False

    # 최근 3선발 ERA는 별도로 계산 필요 (pybaseball game log 필요)
    # 현재는 시즌 ERA를 대용으로 사용
    features["era_L3"] = stats.era  # TODO: 실제 최근 3경기 ERA로 교체

    return features


def _imputed_pitcher_features(avg: dict) -> dict:
    return {
        "era_season": avg["era"],
        "whip_season": avg["whip"],
        "k9_season": avg["k9"],
        "ip_season": float("nan"),
        "days_rest": float("nan"),
        "is_fatigued": False,
        "era_L3": avg["era"],
        "is_ace": False,
        "is_imputed_pitcher": True,
    }
