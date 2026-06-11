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
        from app.pipeline.player_stats_aggregator import get_db_pitcher_stats
        db_stats = await get_db_pitcher_stats(db, name, team_short, season)
        if db_stats:
            return {
                "era": db_stats["era"],
                "whip": db_stats["whip"],
                "k9": db_stats["k9"],
            }

        from app.models.kbo_stats import KboPitcherStat
        for s in [season, season - 1]:
            for extra_cond in [
                and_(KboPitcherStat.name == name, KboPitcherStat.team_short == team_short, KboPitcherStat.season == s),
                and_(KboPitcherStat.name == name, KboPitcherStat.season == s),
            ]:
                row = (await db.execute(select(KboPitcherStat).where(extra_cond))).scalar_one_or_none()
                if row:
                    return {"era": row.era, "whip": row.whip, "k9": row.k9}
        logger.warning(f"[KBO pitcher] 스탯 없음: name={name!r} team={team_short!r} season={season} → 임시값 사용")
        # 같은 팀 투수 목록 출력 (정확한 이름 불일치 파악용)
        team_pitchers = (await db.execute(
            select(KboPitcherStat.name, KboPitcherStat.team_short, KboPitcherStat.season)
            .where(
                KboPitcherStat.team_short == team_short,
                KboPitcherStat.season.in_([season, season - 1]),
            )
            .limit(20)
        )).all()
        logger.warning(f"[KBO pitcher] 같은 팀({team_short}) DB 목록: {[(r.name, r.season) for r in team_pitchers]}")

        # 유니코드 정규화 후 재시도 (NFC ↔ NFD 불일치 대응)
        import unicodedata
        norm_name = unicodedata.normalize("NFC", name)
        if norm_name != name:
            for s in [season, season - 1]:
                row = (await db.execute(
                    select(KboPitcherStat).where(
                        KboPitcherStat.name == norm_name,
                        KboPitcherStat.season == s,
                    )
                )).scalar_one_or_none()
                if row:
                    logger.info(f"[KBO pitcher] NFC 정규화로 매칭 성공: {name!r} → {norm_name!r}")
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


async def get_pitcher_vs_team_stats(
    db: AsyncSession,
    pitcher_name: Optional[str],
    opponent_team_id: int,
    league: str,
    cutoff_date: date,
    seasons: int = 2,
) -> dict:
    """
    선발투수 vs 특정 상대팀 전적 (DB 경기 결과 기반)
    Returns: {
        "games": 경기수,
        "era": ERA,
        "avg_runs_allowed": 평균 실점,
        "wins": 승수,
        "losses": 패수,
    }
    """
    from datetime import timedelta
    from app.models import Game, Team
    from sqlalchemy import or_

    if not pitcher_name:
        return {}

    cutoff_start = date(cutoff_date.year - seasons, cutoff_date.month, cutoff_date.day)

    # 해당 투수가 선발로 등판한 경기 중 상대팀이 opponent인 경기 조회
    stmt = (
        select(Game)
        .where(
            and_(
                Game.status == "final",
                Game.game_date < cutoff_date,
                Game.game_date >= cutoff_start,
                Game.league == league,
                or_(
                    and_(
                        Game.home_starter_name == pitcher_name,
                        Game.away_team_id == opponent_team_id,
                    ),
                    and_(
                        Game.away_starter_name == pitcher_name,
                        Game.home_team_id == opponent_team_id,
                    ),
                ),
                Game.home_score.isnot(None),
                Game.away_score.isnot(None),
            )
        )
        .order_by(Game.game_date.desc())
        .limit(30)
    )
    result = await db.execute(stmt)
    games = result.scalars().all()

    if not games:
        return {}

    wins = 0
    losses = 0
    total_runs_allowed = 0
    total_innings = 0  # 추정 이닝 (경기당 평균 6이닝 가정)

    for g in games:
        is_home_pitcher = g.home_starter_name == pitcher_name
        runs_allowed = g.away_score if is_home_pitcher else g.home_score
        pitcher_team_won = (
            g.home_score > g.away_score if is_home_pitcher
            else g.away_score > g.home_score
        )
        if pitcher_team_won:
            wins += 1
        else:
            losses += 1
        total_runs_allowed += (runs_allowed or 0)
        total_innings += 6  # 선발 평균 이닝 추정

    n = len(games)
    era = (total_runs_allowed * 9 / total_innings) if total_innings > 0 else None

    return {
        "games": n,
        "era": round(era, 2) if era is not None else None,
        "avg_runs_allowed": round(total_runs_allowed / n, 2) if n > 0 else None,
        "wins": wins,
        "losses": losses,
    }


async def get_bullpen_recent_appearances(
    db: AsyncSession,
    team_id: int,
    cutoff_date: date,
    days: int = 3,
) -> dict:
    """
    팀 불펜 최근 등판 횟수 기반 실제 피로도
    DB 경기 결과에서 최근 N일 경기 수 + 실점으로 근사
    Returns: {
        "appearances_L3": 최근 3일 경기 수,
        "runs_allowed_L3": 최근 3경기 평균 실점,
        "fatigue_score": 0~1 피로도 점수,
    }
    """
    from datetime import timedelta
    from app.models import Game

    cutoff_start = cutoff_date - timedelta(days=days)
    stmt = (
        select(Game)
        .where(
            and_(
                Game.status == "final",
                Game.game_date < cutoff_date,
                Game.game_date >= cutoff_start,
                (Game.home_team_id == team_id) | (Game.away_team_id == team_id),
            )
        )
        .order_by(Game.game_date.desc())
    )
    result = await db.execute(stmt)
    games = result.scalars().all()

    if not games:
        return {"appearances_L3": 0, "runs_allowed_L3": float("nan"), "fatigue_score": 0.0}

    n = len(games)
    total_ra = 0
    for g in games:
        is_home = g.home_team_id == team_id
        ra = g.away_score if is_home else g.home_score
        total_ra += (ra or 0)

    avg_ra = total_ra / n
    # 피로도: 3일에 3경기=1.0, 2경기=0.67, 1경기=0.33 (연속 경기일수록 불펜 소진)
    fatigue_score = min(n / 3.0, 1.0)

    return {
        "appearances_L3": n,
        "runs_allowed_L3": round(avg_ra, 2),
        "fatigue_score": round(fatigue_score, 3),
    }
