"""
주간 KBO 스탯 수집 작업 (스케줄러 내부 실행용)
statiz.co.kr에서 투수/타선/불펜 스탯을 스크래핑한 뒤 DB에 직접 upsert합니다.
"""
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


async def run(season: int) -> None:
    """스케줄러에서 호출되는 진입점"""
    from app.config import settings
    if not settings.statiz_enabled:
        logger.info("[stats_upload] statiz 비활성 — 스킵 (backfill-player-stats 사용)")
        return

    # upload_stats.py의 스크래핑 함수 재사용
    root = Path(__file__).resolve().parents[3]  # backend/
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        import httpx
        from upload_stats import (
            statiz_login,
            scrape_pitchers,
            scrape_recent_pitcher_stats,
            scrape_team_batting,
            calc_team_bullpen,
            BASE_HEADERS,
        )
    except ImportError as e:
        logger.error(f"upload_stats 모듈 임포트 실패: {e}")
        return

    logger.info(f"[stats_upload] season={season} 스크래핑 시작")
    with httpx.Client(timeout=30, follow_redirects=True, headers=BASE_HEADERS) as client:
        if not statiz_login(client, season=season):
            logger.error(
                "[stats_upload] statiz 로그인 실패 — Railway Variables에 STATIZ_ID/STATIZ_PW 확인, "
                f"브라우저에서 statiz.co.kr {season} 투수 스탯 페이지 접속 가능한지 확인"
            )
            return

        pitchers = scrape_pitchers(client, season)
        if not pitchers:
            client.cookies.clear()
            if statiz_login(client, season=season):
                pitchers = scrape_pitchers(client, season)
        if not pitchers:
            logger.error(f"[stats_upload] 투수 스탯 수집 실패 (season={season})")
            return

        recent_map = scrape_recent_pitcher_stats(client, season, days=14)
        for p in pitchers:
            key = f"{p['name']}:{p['team_short']}"
            recent = recent_map.get(key, {})
            p["recent_era"] = recent.get("recent_era")
            p["recent_whip"] = recent.get("recent_whip")

        team_batting = scrape_team_batting(client, season)
        team_bullpen = calc_team_bullpen(pitchers)

    logger.info(
        f"[stats_upload] 수집 완료 — 투수 {len(pitchers)}명, "
        f"팀타선 {len(team_batting)}팀, 불펜 {len(team_bullpen)}팀"
    )

    await _upsert_to_db(season, pitchers, team_batting, team_bullpen)

    # statiz → player_season_stats 시드 (이후 경기별 집계로 statiz 대체)
    try:
        from app.core.database import AsyncSessionLocal
        from app.pipeline.player_stats_aggregator import seed_season_from_statiz
        async with AsyncSessionLocal() as db:
            await seed_season_from_statiz(db, season)
    except Exception as e:
        logger.warning(f"[stats_upload] player_season 시드 실패: {e}")

    logger.info("[stats_upload] DB 업로드 완료")


async def _upsert_to_db(
    season: int,
    pitchers: list[dict],
    team_batting: list[dict],
    team_bullpen: list[dict],
) -> None:
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.core.database import AsyncSessionLocal
    from app.models.kbo_stats import (
        KboPitcherStat,
        KboTeamBattingStat,
        KboTeamBullypenStat,
    )

    async with AsyncSessionLocal() as db:
        for p in pitchers:
            vals = dict(
                season=season, name=p["name"], team_short=p["team_short"],
                era=p["era"], whip=p["whip"], k9=p["k9"], ip=p["ip"],
            )
            upd = {"era": p["era"], "whip": p["whip"], "k9": p["k9"], "ip": p["ip"]}
            for opt in ("gs", "handedness", "recent_era", "recent_whip"):
                if p.get(opt) is not None:
                    vals[opt] = p[opt]
                    upd[opt] = p[opt]
            stmt = pg_insert(KboPitcherStat).values(**vals).on_conflict_do_update(
                constraint="uq_kbo_pitcher", set_=upd,
            )
            await db.execute(stmt)

        for t in team_batting:
            stmt = pg_insert(KboTeamBattingStat).values(
                season=season, team_short=t["team_short"],
                ops=t["ops"], wrc_plus=t["wrc_plus"], k_rate=t["k_rate"],
            ).on_conflict_do_update(
                constraint="uq_kbo_team_batting",
                set_={"ops": t["ops"], "wrc_plus": t["wrc_plus"], "k_rate": t["k_rate"]},
            )
            await db.execute(stmt)

        for b in team_bullpen:
            stmt = pg_insert(KboTeamBullypenStat).values(
                season=season, team_short=b["team_short"],
                bullpen_era=b["bullpen_era"], bullpen_whip=b["bullpen_whip"],
                bullpen_count=b["bullpen_count"],
            ).on_conflict_do_update(
                constraint="uq_kbo_team_bullpen",
                set_={
                    "bullpen_era": b["bullpen_era"],
                    "bullpen_whip": b["bullpen_whip"],
                    "bullpen_count": b["bullpen_count"],
                },
            )
            await db.execute(stmt)

        await db.commit()
