"""
선발투수 피처 계산
시즌 ERA/WHIP/K9/FIP, 최근 3선발 ERA, 휴식일수
MLB: mlb_pitcher_stats DB 테이블 우선, 폴백 pybaseball real-time
KBO: kbo_pitcher_stats DB 테이블
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
    """KBO 선발투수 개인 ERA 단일값 반환 (하위 호환)"""
    stats = await get_kbo_starter_stats(name, team_short, season, db)
    return stats.get("era") if stats else None


async def get_kbo_starter_stats(
    name: Optional[str],
    team_short: str,
    season: int,
    db: Optional[AsyncSession] = None,
) -> Optional[dict]:
    """KBO 선발투수 개인 스탯 (era, whip, k9) 반환
    이름 미지정 또는 데이터 없으면 None 반환
    현 시즌 데이터 없으면 직전 시즌으로 폴백
    """
    if not name:
        return None
    if db is not None:
        from app.models.kbo_stats import KboPitcherStat
        for s in [season, season - 1]:
            for extra_cond in [
                and_(KboPitcherStat.name == name, KboPitcherStat.team_short == team_short, KboPitcherStat.season == s),
                and_(KboPitcherStat.name == name, KboPitcherStat.season == s),
            ]:
                row = (await db.execute(select(KboPitcherStat).where(extra_cond))).scalar_one_or_none()
                if row:
                    return {"era": row.era, "whip": row.whip, "k9": row.k9}
    return None


async def get_kbo_bullpen_stats(
    team_short: str,
    season: int,
    db: AsyncSession,
) -> Optional[dict]:
    """KBO 팀 불펜 스탯 — kbo_pitcher_stats에서 gs=0 또는 gs<5인 투수 IP 가중 평균
    kbo_team_bullpen_stats 테이블이 있으면 우선 사용, 없으면 개별 데이터로 계산
    """
    from sqlalchemy import and_
    from app.models.kbo_stats import KboTeamBullypenStat, KboPitcherStat

    # 1) 팀 집계 테이블 우선 조회
    for s in [season, season - 1]:
        row = (await db.execute(
            select(KboTeamBullypenStat).where(
                and_(KboTeamBullypenStat.team_short == team_short, KboTeamBullypenStat.season == s)
            )
        )).scalar_one_or_none()
        if row:
            return {"era": row.bullpen_era, "whip": row.bullpen_whip}

    # 2) 개별 투수 데이터에서 계산 (gs < 5 = 불펜 투수)
    for s in [season, season - 1]:
        pitchers = (await db.execute(
            select(KboPitcherStat).where(
                and_(
                    KboPitcherStat.team_short == team_short,
                    KboPitcherStat.season == s,
                    KboPitcherStat.ip >= 1,
                )
            )
        )).scalars().all()

        bullpen = [p for p in pitchers if (p.gs is not None and p.gs < 5) or (p.gs is None and p.ip < 30)]
        if bullpen:
            total_ip = sum(p.ip for p in bullpen)
            if total_ip > 0:
                era = sum(p.era * p.ip for p in bullpen) / total_ip
                whip = sum(p.whip * p.ip for p in bullpen) / total_ip
                return {"era": era, "whip": whip}

    return None


async def get_mlb_starter_stats(
    name: Optional[str],
    team_short: str,
    season: int,
    db: Optional[AsyncSession] = None,
) -> Optional[dict]:
    """MLB 선발투수 개인 스탯 (era, fip, whip, k9, handedness) 반환
    DB 우선, 없으면 None (호출자가 pybaseball fallback 처리)
    현 시즌 데이터 없으면 직전 시즌 폴백
    """
    if not name or db is None:
        return None
    from app.models.mlb_stats import MlbPitcherStat
    for s in [season, season - 1]:
        for cond in [
            and_(MlbPitcherStat.name == name, MlbPitcherStat.team_short == team_short, MlbPitcherStat.season == s),
            and_(MlbPitcherStat.name == name, MlbPitcherStat.season == s),
        ]:
            row = (await db.execute(select(MlbPitcherStat).where(cond))).scalar_one_or_none()
            if row:
                return {
                    "era": row.era,
                    "fip": row.fip,
                    "whip": row.whip,
                    "k9": row.k9,
                    "bb9": row.bb9,
                    "ip": row.ip,
                    "handedness": row.handedness,
                    "recent_era": row.recent_era,
                    "recent_whip": row.recent_whip,
                    "home_era": getattr(row, "home_era", None),
                    "away_era": getattr(row, "away_era", None),
                    "fastball_pct": getattr(row, "fastball_pct", None),
                    "avg_velocity": getattr(row, "avg_velocity", None),
                }
    return None


async def get_mlb_bullpen_stats(
    team_short: str,
    season: int,
    db: AsyncSession,
) -> Optional[dict]:
    """MLB 팀 불펜 스탯 — mlb_team_bullpen_stats 우선, 없으면 개별 투수 집계"""
    from app.models.mlb_stats import MlbTeamBullypenStat, MlbPitcherStat

    # 1) 집계 테이블 우선
    for s in [season, season - 1]:
        row = (await db.execute(
            select(MlbTeamBullypenStat).where(
                and_(MlbTeamBullypenStat.team_short == team_short, MlbTeamBullypenStat.season == s)
            )
        )).scalar_one_or_none()
        if row:
            return {"era": row.bullpen_era, "whip": row.bullpen_whip, "k9": row.bullpen_k9}

    # 2) 개별 투수 데이터에서 집계 (GS/G < 0.3 인 투수)
    for s in [season, season - 1]:
        pitchers = (await db.execute(
            select(MlbPitcherStat).where(
                and_(MlbPitcherStat.team_short == team_short, MlbPitcherStat.season == s, MlbPitcherStat.ip >= 5)
            )
        )).scalars().all()
        bullpen = [p for p in pitchers if (p.g or 1) > 0 and ((p.gs or 0) / (p.g or 1)) < 0.3]
        if bullpen:
            total_ip = sum(p.ip for p in bullpen)
            if total_ip > 0:
                era = sum(p.era * p.ip for p in bullpen) / total_ip
                whip = sum(p.whip * p.ip for p in bullpen) / total_ip
                k9_vals = [p.k9 * p.ip for p in bullpen if p.k9]
                k9 = sum(k9_vals) / total_ip if k9_vals else None
                return {"era": era, "whip": whip, "k9": k9}

    return None


async def get_npb_starter_stats(
    name: Optional[str],
    team_short: str,
    season: int,
    db: Optional[AsyncSession] = None,
) -> Optional[dict]:
    """NPB 선발투수 스탯 (era, whip, k9, handedness) — KBO와 동일 구조"""
    if not name or db is None:
        return None
    from app.models.npb_stats import NpbPitcherStat
    for s in [season, season - 1]:
        for cond in [
            and_(NpbPitcherStat.name == name, NpbPitcherStat.team_short == team_short, NpbPitcherStat.season == s),
            and_(NpbPitcherStat.name == name, NpbPitcherStat.season == s),
        ]:
            row = (await db.execute(select(NpbPitcherStat).where(cond))).scalar_one_or_none()
            if row:
                return {
                    "era": row.era, "whip": row.whip, "k9": row.k9,
                    "ip": row.ip, "handedness": row.handedness,
                    "recent_era": row.recent_era, "recent_whip": row.recent_whip,
                }
    return None


async def get_npb_bullpen_stats(team_short: str, season: int, db: AsyncSession) -> Optional[dict]:
    """NPB 팀 불펜 스탯"""
    from app.models.npb_stats import NpbTeamBullypenStat, NpbPitcherStat
    for s in [season, season - 1]:
        row = (await db.execute(
            select(NpbTeamBullypenStat).where(
                and_(NpbTeamBullypenStat.team_short == team_short, NpbTeamBullypenStat.season == s)
            )
        )).scalar_one_or_none()
        if row:
            return {"era": row.bullpen_era, "whip": row.bullpen_whip}
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

    # MLB: DB에서 이름 기반 조회 우선 (mlb_pitcher_stats)
    if league == "MLB" and pitcher.name:
        team_short = None
        if pitcher.team_id:
            from app.models import Team
            team_res = await db.execute(select(Team).where(Team.id == pitcher.team_id))
            team = team_res.scalar_one_or_none()
            team_short = team.short_name if team else None
        db_stats = await get_mlb_starter_stats(pitcher.name, team_short or "", season, db)
        if db_stats and db_stats["ip"] >= 5:
            return {
                "era_season": db_stats["era"],
                "whip_season": db_stats["whip"],
                "k9_season": db_stats["k9"],
                "fip_season": db_stats.get("fip"),
                "ip_season": db_stats["ip"],
                "days_rest": float("nan"),
                "is_fatigued": False,
                "era_L3": db_stats.get("recent_era") or db_stats["era"],
                "is_ace": False,
                "is_imputed_pitcher": False,
                "handedness": db_stats.get("handedness") or "R",
                "home_era": db_stats.get("home_era"),
                "away_era": db_stats.get("away_era"),
                "fastball_pct": db_stats.get("fastball_pct"),
                "avg_velocity": db_stats.get("avg_velocity"),
            }

    # pybaseball에서 시즌 통계 가져오기 (비동기, MLB fallback 또는 다른 리그)
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
        "fip_season": None,
        "ip_season": stats.ip,
        "is_imputed_pitcher": False,
        "is_ace": False,
        "handedness": "R",
    }

    # 마지막 등판일로 휴식일수 계산
    if stats.last_appearance_date:
        features["days_rest"] = (game_date - stats.last_appearance_date).days
        features["is_fatigued"] = features["days_rest"] < 4
    else:
        features["days_rest"] = float("nan")
        features["is_fatigued"] = False

    features["era_L3"] = stats.era

    return features


def _imputed_pitcher_features(avg: dict) -> dict:
    return {
        "era_season": avg["era"],
        "whip_season": avg["whip"],
        "k9_season": avg["k9"],
        "fip_season": None,
        "ip_season": float("nan"),
        "days_rest": float("nan"),
        "is_fatigued": False,
        "era_L3": avg["era"],
        "is_ace": False,
        "is_imputed_pitcher": True,
        "handedness": "R",
        # 확장 피처
        "home_era": None,
        "away_era": None,
        "fastball_pct": None,
        "avg_velocity": None,
    }
