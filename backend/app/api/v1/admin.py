"""
관리자용 수동 트리거 엔드포인트
"""
import logging
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db

router = APIRouter()
logger = logging.getLogger(__name__)

# 백그라운드 태스크 참조 보관 (GC 방지)
_background_tasks: set = set()

def _create_background_task(coro):
    """태스크를 생성하고 GC 방지를 위해 참조를 보관"""
    import asyncio
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


# ── 스탯 업로드 스키마 ──────────────────────────────────────
class PitcherStatIn(BaseModel):
    name: str
    team_short: str
    era: float
    whip: float
    k9: float
    ip: float
    gs: Optional[int] = None               # 선발 등판수 (0=불펜)
    handedness: Optional[str] = None       # "L" or "R"
    recent_era: Optional[float] = None     # 최근 14일 ERA
    recent_whip: Optional[float] = None    # 최근 14일 WHIP

class TeamBattingStatIn(BaseModel):
    team_short: str
    ops: float
    wrc_plus: float
    k_rate: float

class TeamBullpenStatIn(BaseModel):
    team_short: str
    bullpen_era: float
    bullpen_whip: float
    bullpen_count: int = 0

class TeamBattingSplitStatIn(BaseModel):
    team_short: str
    split: str   # "vs_lhp" or "vs_rhp"
    ops: float
    pa: int = 0

class UploadStatsPayload(BaseModel):
    season: int
    pitchers: List[PitcherStatIn] = []
    team_batting: List[TeamBattingStatIn] = []
    team_bullpen: List[TeamBullpenStatIn] = []
    team_batting_splits: List[TeamBattingSplitStatIn] = []


@router.post("/upload-stats")
async def upload_stats(payload: UploadStatsPayload, db: AsyncSession = Depends(get_db)):
    """로컬에서 수집한 KBO 스탯을 DB에 저장 (upsert)"""
    from app.models.kbo_stats import KboPitcherStat, KboTeamBattingStat, KboTeamBullypenStat, KboTeamBattingSplitStat

    season = payload.season

    # 투수 upsert
    if payload.pitchers:
        for p in payload.pitchers:
            vals = dict(season=season, name=p.name, team_short=p.team_short,
                        era=p.era, whip=p.whip, k9=p.k9, ip=p.ip)
            if p.gs is not None:
                vals["gs"] = p.gs
            if p.handedness:
                vals["handedness"] = p.handedness
            if p.recent_era is not None:
                vals["recent_era"] = p.recent_era
            if p.recent_whip is not None:
                vals["recent_whip"] = p.recent_whip
            upd = {"era": p.era, "whip": p.whip, "k9": p.k9, "ip": p.ip}
            if p.gs is not None:
                upd["gs"] = p.gs
            if p.handedness:
                upd["handedness"] = p.handedness
            if p.recent_era is not None:
                upd["recent_era"] = p.recent_era
            if p.recent_whip is not None:
                upd["recent_whip"] = p.recent_whip
            stmt = insert(KboPitcherStat).values(**vals).on_conflict_do_update(
                constraint="uq_kbo_pitcher", set_=upd,
            )
            await db.execute(stmt)

    # 팀 타선 upsert
    if payload.team_batting:
        for t in payload.team_batting:
            stmt = insert(KboTeamBattingStat).values(
                season=season, team_short=t.team_short,
                ops=t.ops, wrc_plus=t.wrc_plus, k_rate=t.k_rate,
            ).on_conflict_do_update(
                constraint="uq_kbo_team_batting",
                set_={"ops": t.ops, "wrc_plus": t.wrc_plus, "k_rate": t.k_rate},
            )
            await db.execute(stmt)

    # 팀 불펜 upsert
    if payload.team_bullpen:
        for b in payload.team_bullpen:
            stmt = insert(KboTeamBullypenStat).values(
                season=season, team_short=b.team_short,
                bullpen_era=b.bullpen_era, bullpen_whip=b.bullpen_whip, bullpen_count=b.bullpen_count,
            ).on_conflict_do_update(
                constraint="uq_kbo_team_bullpen",
                set_={"bullpen_era": b.bullpen_era, "bullpen_whip": b.bullpen_whip, "bullpen_count": b.bullpen_count},
            )
            await db.execute(stmt)

    # 팀 타선 스플릿 upsert
    if payload.team_batting_splits:
        for s in payload.team_batting_splits:
            stmt = insert(KboTeamBattingSplitStat).values(
                season=season, team_short=s.team_short, split=s.split,
                ops=s.ops, pa=s.pa,
            ).on_conflict_do_update(
                constraint="uq_kbo_team_batting_split",
                set_={"ops": s.ops, "pa": s.pa},
            )
            await db.execute(stmt)

    await db.commit()
    logger.info(
        f"스탯 업로드 완료: season={season}, 투수={len(payload.pitchers)}, "
        f"팀타선={len(payload.team_batting)}, 불펜={len(payload.team_bullpen)}, "
        f"스플릿={len(payload.team_batting_splits)}"
    )
    return {
        "status": "ok",
        "season": season,
        "pitchers_upserted": len(payload.pitchers),
        "team_batting_upserted": len(payload.team_batting),
        "team_bullpen_upserted": len(payload.team_bullpen),
        "splits_upserted": len(payload.team_batting_splits),
    }


class PitcherHandednessIn(BaseModel):
    name: str
    team_short: str
    handedness: str  # "L" or "R"


class UploadHandednessPayload(BaseModel):
    season: int
    pitchers: List[PitcherHandednessIn]


@router.post("/upload-handedness")
async def upload_handedness(payload: UploadHandednessPayload, db: AsyncSession = Depends(get_db)):
    """투수 좌/우손만 등록 (ERA 등 기존 백필 스탯은 유지)"""
    from sqlalchemy import select, update
    from app.models.kbo_stats import KboPitcherStat
    from app.models.kbo_player_stats import KboPlayerSeasonStat

    season = payload.season
    hand = {"L", "R"}
    updated_pitcher = 0
    inserted_pitcher = 0
    updated_player = 0

    for p in payload.pitchers:
        h = p.handedness.upper()
        if h not in hand:
            continue
        if h == "L":
            h = "L"
        else:
            h = "R"

        existing = (await db.execute(
            select(KboPitcherStat).where(
                KboPitcherStat.season == season,
                KboPitcherStat.name == p.name,
                KboPitcherStat.team_short == p.team_short,
            )
        )).scalar_one_or_none()

        if existing:
            existing.handedness = h
            updated_pitcher += 1
        else:
            await db.execute(
                insert(KboPitcherStat).values(
                    season=season,
                    name=p.name,
                    team_short=p.team_short,
                    era=4.50,
                    whip=1.35,
                    k9=7.0,
                    ip=1.0,
                    gs=0,
                    handedness=h,
                )
            )
            inserted_pitcher += 1

        ps_result = await db.execute(
            update(KboPlayerSeasonStat)
            .where(
                KboPlayerSeasonStat.season == season,
                KboPlayerSeasonStat.name == p.name,
                KboPlayerSeasonStat.team_short == p.team_short,
                KboPlayerSeasonStat.role == "pitcher",
            )
            .values(handedness=h)
        )
        updated_player += ps_result.rowcount

    await db.commit()
    logger.info(
        f"handedness 업로드: season={season}, "
        f"pitcher_stats 갱신={updated_pitcher} 신규={inserted_pitcher}, "
        f"player_season 갱신={updated_player}"
    )
    return {
        "status": "ok",
        "season": season,
        "pitcher_stats_updated": updated_pitcher,
        "pitcher_stats_inserted": inserted_pitcher,
        "player_season_updated": updated_player,
    }


@router.post("/retrain")
async def trigger_retrain(league: str = Query(default=None)):
    """모델 수동 재학습 트리거. league=MLB 로 지정 가능 (기본: 설정값)"""
    import asyncio

    from app.config import settings
    target = league.upper() if league else settings.league

    async def _run(lg: str):
        from app.ml.trainer import Trainer
        trainer = Trainer(league=lg)
        await trainer.retrain()
        logger.info(f"{lg} 모델 재학습 완료")

    _create_background_task(_run(target))
    logger.info(f"수동 재학습 트리거: {target}")
    return {"status": "started", "league": target}


@router.post("/collect")
async def trigger_collect(
    target_date: str = Query(default=None),
    force: bool = Query(default=False),
    league: str = Query(default=None, description="KBO 또는 MLB (지정 시 해당 리그만 수집)"),
):
    """경기 수집 + 예측 수동 트리거. force=true면 기존 예측 삭제 후 재생성. league=MLB면 MLB만 수집"""
    import asyncio
    from datetime import datetime

    parsed_date = datetime.strptime(target_date, "%Y-%m-%d").date() if target_date else None
    d = parsed_date or date.today()
    target_league = league.upper() if league else None

    if force:
        from sqlalchemy import delete
        from app.core.database import AsyncSessionLocal
        from app.models import Game, Prediction
        from sqlalchemy import select, and_
        async with AsyncSessionLocal() as db:
            cond = [Game.game_date == d]
            if target_league:
                cond.append(Game.league == target_league)
            games = (await db.execute(select(Game).where(and_(*cond)))).scalars().all()
            for game in games:
                await db.execute(delete(Prediction).where(Prediction.game_id == game.id))
            await db.commit()
        logger.info(f"기존 예측 삭제 완료: {d} (league={target_league or '전체'})")

    async def _run():
        from app.pipeline.etl_runner import ETLRunner
        from app.ml.predictor import Predictor
        from app.core.database import AsyncSessionLocal
        from app.models import Game, Prediction
        from sqlalchemy import select, and_, or_

        leagues = [target_league] if target_league else ["KBO", "MLB"]

        # 경기 수집
        for lg in leagues:
            try:
                runner = ETLRunner(league=lg)
                await runner.run_for_date(d)
            except Exception as ex:
                logger.warning(f"{lg} 경기 수집 실패: {ex}")

        # 예측 생성
        async with AsyncSessionLocal() as db:
            cond = [Game.game_date == d]
            if target_league:
                cond.append(Game.league == target_league)
            if force:
                cond.append(or_(Game.status == "scheduled", Game.status == "final", Game.status == "in_progress"))
            else:
                cond.append(Game.status == "scheduled")
            games = (await db.execute(select(Game).where(and_(*cond)))).scalars().all()

            try:
                predictor = Predictor()
            except Exception as ex:
                logger.error(f"예측 모델 로드 실패: {ex}")
                return

            predicted = 0
            for game in games:
                existing = await db.execute(
                    select(Prediction).where(
                        Prediction.game_id == game.id,
                        Prediction.model_version == predictor.model_version,
                    )
                )
                if existing.scalar_one_or_none():
                    continue
                try:
                    result = await predictor.predict(game.id, db)
                    if result:
                        db.add(Prediction(**result))
                        predicted += 1
                except Exception as ex:
                    logger.warning(f"game {game.id} 예측 실패: {ex}")
            await db.commit()
        logger.info(f"수집+예측 완료: {d} (leagues={leagues}, predicted={predicted})")

        # 캐시 자동 플러시 (수집한 리그 날짜 기준)
        from app.core.redis_client import cache_delete
        for lg in leagues:
            await cache_delete(f"games:today:{lg}:{d.isoformat()}")
        logger.info(f"캐시 플러시 완료: {leagues} {d}")

    _create_background_task(_run())
    return {"status": "started", "date": str(d), "force": force, "league": target_league or "전체"}


@router.post("/collect-mlb-week")
async def trigger_collect_mlb_week():
    """오늘부터 7일치 MLB 경기 수집 + 예측 수동 트리거"""
    import asyncio
    from app.core.scheduler import _run_mlb_next_day_collect

    logger.info("수동 트리거: MLB 7일치 경기 수집 시작")
    asyncio.create_task(_run_mlb_next_day_collect())
    return {"status": "started", "days": 7}


@router.delete("/predictions")
async def delete_predictions(target_date: str = Query(...)):
    """특정 날짜 예측 삭제"""
    from sqlalchemy import delete
    from app.core.database import AsyncSessionLocal
    from app.models import Game, Prediction
    from sqlalchemy import select
    from datetime import datetime

    d = datetime.strptime(target_date, "%Y-%m-%d").date()
    async with AsyncSessionLocal() as db:
        games = (await db.execute(select(Game).where(Game.game_date == d))).scalars().all()
        deleted = 0
        for game in games:
            result = await db.execute(delete(Prediction).where(Prediction.game_id == game.id))
            deleted += result.rowcount
        await db.commit()
    logger.info(f"예측 삭제 완료: {d} ({deleted}건)")
    return {"status": "deleted", "date": str(d), "count": deleted}


@router.post("/lineup/mlb")
async def trigger_mlb_lineup(target_date: str = Query(default=None)):
    """MLB 선발투수/라인업 수동 수집 트리거"""
    from datetime import date as date_cls, datetime
    d = datetime.strptime(target_date, "%Y-%m-%d").date() if target_date else date_cls.today()
    logger.info(f"수동 트리거: MLB 라인업 수집 시작 ({d})")

    async def _run():
        from app.pipeline.lineup_watcher import run_for_date_mlb
        await run_for_date_mlb(d)
        logger.info(f"MLB 라인업 수집 완료: {d}")

    _create_background_task(_run())
    return {"status": "started", "date": str(d), "league": "MLB"}


@router.post("/lineup")
async def trigger_lineup(target_date: str = Query(default=None), force: bool = Query(default=False)):
    """라인업 수동 수집 트리거. force=true면 lineup_locked 초기화 후 재수집"""
    import asyncio
    from datetime import date as date_cls, datetime

    if target_date:
        d = datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        d = date_cls.today()

    if force:
        from sqlalchemy import update as sa_update
        from app.core.database import AsyncSessionLocal
        from app.models import Game
        async with AsyncSessionLocal() as db:
            await db.execute(
                sa_update(Game)
                .where(Game.game_date == d, Game.league == "KBO", Game.status == "scheduled")
                .values(lineup_locked=False, lineup_locked_at=None,
                        home_starter_name=None, away_starter_name=None)
            )
            await db.commit()
        logger.info(f"라인업 초기화 완료: {d}")

    logger.info(f"수동 트리거: 라인업 수집 시작 ({d}, force={force})")

    async def _run():
        from app.pipeline.lineup_watcher import run_for_date
        await run_for_date(d)
        logger.info(f"라인업 수집 완료: {d}")

    _create_background_task(_run())
    return {"status": "started", "date": str(d), "force": force}


class LineupPlayerIn(BaseModel):
    order: int
    name: str
    position: str = ""

class ManualGameLineupIn(BaseModel):
    game_id: int
    home_starter: Optional[str] = None
    away_starter: Optional[str] = None
    home_lineup: List[LineupPlayerIn] = []
    away_lineup: List[LineupPlayerIn] = []

class ManualLineupPayload(BaseModel):
    games: List[ManualGameLineupIn]


@router.post("/lineup/manual")
async def manual_lineup(payload: ManualLineupPayload, db: AsyncSession = Depends(get_db)):
    """수동 라인업 직접 입력 → DB 즉시 반영 + 예측 재실행"""
    from datetime import datetime, timezone
    from sqlalchemy import select, update
    from app.models import Game

    results = []
    for g in payload.games:
        row = (await db.execute(select(Game).where(Game.id == g.game_id))).scalar_one_or_none()
        if not row:
            results.append({"game_id": g.game_id, "status": "not_found"})
            continue

        now = datetime.now(timezone.utc)
        updates: dict = {"updated_at": now}
        if g.home_starter:
            updates["home_starter_name"] = g.home_starter
        if g.away_starter:
            updates["away_starter_name"] = g.away_starter
        if g.home_lineup:
            updates["home_lineup_json"] = [p.model_dump() for p in g.home_lineup]
        if g.away_lineup:
            updates["away_lineup_json"] = [p.model_dump() for p in g.away_lineup]

        final_home_sp = g.home_starter or row.home_starter_name
        final_away_sp = g.away_starter or row.away_starter_name
        if final_home_sp and final_away_sp:
            updates["lineup_locked"] = True
            updates["lineup_locked_at"] = now

        await db.execute(update(Game).where(Game.id == row.id).values(**updates))
        await db.commit()

        # 예측 재실행
        try:
            from app.pipeline.lineup_watcher import _retrigger_prediction
            await _retrigger_prediction(db, row.id)
            pred_status = "predicted"
        except Exception as e:
            pred_status = f"predict_failed: {e}"

        results.append({
            "game_id": row.id,
            "home_starter": g.home_starter,
            "away_starter": g.away_starter,
            "lineup_locked": updates.get("lineup_locked", False),
            "status": pred_status,
        })

    return {"results": results}


@router.post("/collect-stats")
async def trigger_collect_stats(season: int = Query(default=None)):
    """(비활성) statiz 스탯 수집 — 차단 시 backfill-player-stats 사용"""
    from datetime import date as date_cls
    from app.config import settings

    s = season or date_cls.today().year
    if not settings.statiz_enabled:
        return {
            "status": "skipped",
            "season": s,
            "reason": "statiz 비활성 (STATIZ_ENABLED=false). POST /backfill-player-stats 사용",
        }

    logger.info(f"수동 트리거: KBO 스탯 수집 시작 (season={s})")

    async def _run():
        from app.tasks.stats_upload import run as run_stats
        from app.tasks.compute_splits import run as run_splits
        await run_stats(season=s)
        await run_splits(season=s)
        logger.info(f"KBO 스탯 수집 + 스플릿 계산 완료 (season={s})")

    _create_background_task(_run())
    return {"status": "started", "season": s}


@router.post("/compute-splits")
async def trigger_compute_splits(season: int = Query(default=None)):
    """DB 경기 데이터로 팀 타선 좌/우완 스플릿 OPS 계산"""
    import asyncio
    from datetime import date as date_cls

    s = season or date_cls.today().year
    logger.info(f"수동 트리거: 스플릿 OPS 계산 시작 (season={s})")

    async def _run():
        from app.tasks.compute_splits import run
        await run(season=s)
        logger.info(f"스플릿 OPS 계산 완료 (season={s})")

    _create_background_task(_run())
    return {"status": "started", "season": s}


@router.post("/seed-player-stats")
async def trigger_seed_player_stats(season: int = Query(default=None)):
    """statiz 업로드 데이터 → kbo_player_season_stats 시드 (초기 1회)"""
    from datetime import date as date_cls

    s = season or date_cls.today().year

    async def _run():
        from app.core.database import AsyncSessionLocal
        from app.pipeline.player_stats_aggregator import seed_season_from_statiz
        async with AsyncSessionLocal() as db:
            result = await seed_season_from_statiz(db, s)
        logger.info(f"player_season 시드 완료 (season={s}): {result}")

    _create_background_task(_run())
    return {"status": "started", "season": s, "note": "기존 kbo_pitcher_stats/statiz 타자 캐시에서 시드"}


@router.post("/backfill-player-stats")
async def trigger_backfill_player_stats(season: int = Query(default=None)):
    """종료된 KBO 경기 Naver 박스스코어 일괄 수집 → 자체 선수 스탯 집계"""
    from datetime import date as date_cls

    s = season or date_cls.today().year

    async def _run():
        from app.core.database import AsyncSessionLocal
        from app.pipeline.player_stats_aggregator import backfill_from_final_games
        async with AsyncSessionLocal() as db:
            n = await backfill_from_final_games(db, s)
        logger.info(f"player_stats 백필 완료 (season={s}): {n}경기")

    _create_background_task(_run())
    return {"status": "started", "season": s}


@router.post("/collect-mlb-stats")
async def trigger_collect_mlb_stats(
    season: int = Query(default=None),
    all_seasons: bool = Query(default=False, alias="all"),
):
    """MLB 시즌 스탯 수집 및 DB upsert 수동 트리거
    season: 특정 시즌 (기본: 현재 시즌)
    all=true: 2024-2025 전체 수집
    """
    import asyncio
    from datetime import date as date_cls

    seasons_to_collect: list[int]
    if all_seasons:
        seasons_to_collect = [2024, 2025]
    else:
        seasons_to_collect = [season or date_cls.today().year]

    logger.info(f"수동 트리거: MLB 스탯 수집 시작 (seasons={seasons_to_collect})")

    async def _run():
        from app.collectors.mlb_stats_collector import upsert_mlb_stats
        from app.core.database import AsyncSessionLocal
        results = []
        for s in seasons_to_collect:
            async with AsyncSessionLocal() as db:
                summary = await upsert_mlb_stats(s, db)
                results.append(summary)
                logger.info(f"MLB 스탯 수집 완료: season={s}, {summary}")
        return results

    _create_background_task(_run())
    return {"status": "started", "seasons": seasons_to_collect}


@router.post("/upload-npb-stats")
async def upload_npb_stats(payload: UploadStatsPayload, db: AsyncSession = Depends(get_db)):
    """로컬에서 수집한 NPB 스탯을 DB에 저장 (upsert)"""
    from app.models.npb_stats import NpbPitcherStat, NpbTeamBattingStat, NpbTeamBullypenStat, NpbTeamBattingSplitStat

    season = payload.season

    if payload.pitchers:
        for p in payload.pitchers:
            vals = dict(season=season, name=p.name, team_short=p.team_short,
                        era=p.era, whip=p.whip, k9=p.k9, ip=p.ip)
            if p.gs is not None:
                vals["gs"] = p.gs
            if p.handedness:
                vals["handedness"] = p.handedness
            if p.recent_era is not None:
                vals["recent_era"] = p.recent_era
            if p.recent_whip is not None:
                vals["recent_whip"] = p.recent_whip
            upd = {"era": p.era, "whip": p.whip, "k9": p.k9, "ip": p.ip}
            if p.gs is not None:
                upd["gs"] = p.gs
            if p.handedness:
                upd["handedness"] = p.handedness
            if p.recent_era is not None:
                upd["recent_era"] = p.recent_era
            if p.recent_whip is not None:
                upd["recent_whip"] = p.recent_whip
            stmt = insert(NpbPitcherStat).values(**vals).on_conflict_do_update(
                constraint="uq_npb_pitcher", set_=upd,
            )
            await db.execute(stmt)

    if payload.team_batting:
        for t in payload.team_batting:
            stmt = insert(NpbTeamBattingStat).values(
                season=season, team_short=t.team_short,
                ops=t.ops, wrc_plus=t.wrc_plus, k_rate=t.k_rate,
            ).on_conflict_do_update(
                constraint="uq_npb_team_batting",
                set_={"ops": t.ops, "wrc_plus": t.wrc_plus, "k_rate": t.k_rate},
            )
            await db.execute(stmt)

    if payload.team_bullpen:
        for b in payload.team_bullpen:
            stmt = insert(NpbTeamBullypenStat).values(
                season=season, team_short=b.team_short,
                bullpen_era=b.bullpen_era, bullpen_whip=b.bullpen_whip, bullpen_count=b.bullpen_count,
            ).on_conflict_do_update(
                constraint="uq_npb_team_bullpen",
                set_={"bullpen_era": b.bullpen_era, "bullpen_whip": b.bullpen_whip, "bullpen_count": b.bullpen_count},
            )
            await db.execute(stmt)

    if payload.team_batting_splits:
        for s in payload.team_batting_splits:
            stmt = insert(NpbTeamBattingSplitStat).values(
                season=season, team_short=s.team_short, split=s.split,
                ops=s.ops, pa=s.pa,
            ).on_conflict_do_update(
                constraint="uq_npb_team_batting_split",
                set_={"ops": s.ops, "pa": s.pa},
            )
            await db.execute(stmt)

    await db.commit()
    logger.info(
        f"NPB 스탯 업로드 완료: season={season}, 투수={len(payload.pitchers)}, "
        f"팀타선={len(payload.team_batting)}, 불펜={len(payload.team_bullpen)}, "
        f"스플릿={len(payload.team_batting_splits)}"
    )
    return {
        "status": "ok",
        "season": season,
        "pitchers_upserted": len(payload.pitchers),
        "team_batting_upserted": len(payload.team_batting),
        "team_bullpen_upserted": len(payload.team_bullpen),
        "splits_upserted": len(payload.team_batting_splits),
    }


@router.post("/migrate")
async def trigger_migrate():
    """Alembic 마이그레이션 수동 실행 (alembic upgrade head)"""
    import subprocess
    import sys
    try:
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd="/app",
            capture_output=True,
            text=True,
        )
        output = result.stdout + result.stderr
        logger.info(f"Alembic 결과: {output}")
        if result.returncode != 0:
            return {"status": "error", "message": output}
        return {"status": "ok", "message": output}
    except Exception as e:
        logger.error(f"Alembic 마이그레이션 실패: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/collect-results")
async def trigger_collect_results(
    target_date: str = Query(default=None),
    from_date: str = Query(default=None, description="범위 시작 YYYY-MM-DD (to_date와 함께 사용)"),
    to_date: str = Query(default=None, description="범위 종료 YYYY-MM-DD"),
    league: str = Query(default=None, description="리그 (KBO/MLB, 기본: 전체)"),
):
    """경기 결과 수집 수동 트리거. from_date~to_date 범위 또는 단일 날짜."""
    import asyncio
    from datetime import datetime, timedelta, date as date_cls
    from app.pipeline.etl_runner import ETLRunner

    # 범위 모드
    if from_date and to_date:
        s = date_cls.fromisoformat(from_date)
        e = date_cls.fromisoformat(to_date)
        leagues = [league.upper()] if league else ["KBO", "MLB"]

        async def _run_range():
            cur = s
            while cur <= e:
                for lg in leagues:
                    try:
                        runner = ETLRunner(league=lg)
                        await runner.run_results(cur)
                    except Exception as ex:
                        logger.warning(f"결과 수집 실패 ({lg} {cur}): {ex}")
                cur += timedelta(days=1)
            logger.info(f"범위 결과 수집 완료: {s} ~ {e}")

        _create_background_task(_run_range())
        return {"status": "started", "from": str(s), "to": str(e), "leagues": leagues}

    # 단일 날짜 모드
    if target_date:
        d = datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        d = date_cls.today() - timedelta(days=1)

    leagues = [league.upper()] if league else ["KBO", "MLB"]

    async def _run():
        for lg in leagues:
            runner = ETLRunner(league=lg)
            await runner.run_results(d)
        logger.info(f"경기 결과 수집 완료: {d}")

    _create_background_task(_run())
    return {"status": "started", "date": str(d), "leagues": leagues}


@router.post("/backfill")
async def trigger_backfill(
    start: str = Query(..., description="시작일 YYYY-MM-DD"),
    end: str = Query(..., description="종료일 YYYY-MM-DD"),
    league: str = Query(default=None, description="리그 (KBO/MLB, 기본: 설정값)"),
    skip_weather: bool = Query(default=True),
):
    """과거 경기 결과 백필 (start~end 범위)"""
    import asyncio
    from datetime import datetime
    from app.pipeline.etl_runner import backfill_async

    s = datetime.strptime(start, "%Y-%m-%d").date()
    e = datetime.strptime(end, "%Y-%m-%d").date()
    target_league = league.upper() if league else None

    logger.info(f"백필 트리거: {s} ~ {e}, league={target_league or '설정값'}")

    _create_background_task(backfill_async(s, e, league=target_league, skip_weather=skip_weather))
    return {"status": "started", "start": str(s), "end": str(e), "league": target_league}


@router.post("/backtest")
async def trigger_backtest(
    start: str = Query(..., description="시작일 YYYY-MM-DD"),
    end: str = Query(..., description="종료일 YYYY-MM-DD"),
    league: str = Query(..., description="리그 (KBO/MLB)"),
):
    """백테스트: 해당 기간의 완료된 경기에 예측을 생성하고 was_correct 계산.
    이미 예측이 있는 경기는 건너뜀."""
    from datetime import datetime
    from sqlalchemy import select, and_
    from app.core.database import AsyncSessionLocal
    from app.models import Game, Prediction

    s = datetime.strptime(start, "%Y-%m-%d").date()
    e = datetime.strptime(end, "%Y-%m-%d").date()
    lg = league.upper()

    async def _run_backtest():
        try:
            from app.ml.predictor import Predictor
            logger.info(f"[백테스트] 시작: {lg} {s}~{e}")

            predictor = Predictor(league=lg)
            predicted = 0
            skipped = 0

            async with AsyncSessionLocal() as db:
                # 완료된 경기 중 예측 없는 것 조회
                result = await db.execute(
                    select(Game).where(
                        and_(
                            Game.game_date >= s,
                            Game.game_date <= e,
                            Game.league == lg,
                            Game.status == "final",
                            Game.winner_team_id.isnot(None),
                        )
                    ).order_by(Game.game_date)
                )
                games = result.scalars().all()
                logger.info(f"[백테스트] {lg} {s}~{e}: 대상 {len(games)}경기")

                for game in games:
                    # 이미 예측 있으면 건너뜀
                    existing = await db.execute(
                        select(Prediction).where(Prediction.game_id == game.id).limit(1)
                    )
                    if existing.scalar_one_or_none():
                        skipped += 1
                        continue

                    try:
                        pred_result = await predictor.predict(game.id, db)
                        if pred_result:
                            pred = Prediction(**pred_result)
                            pred.was_correct = (pred_result["predicted_winner_id"] == game.winner_team_id)
                            db.add(pred)
                            predicted += 1
                            if predicted % 50 == 0:
                                await db.commit()
                                logger.info(f"[백테스트] 진행 중: {predicted}경기 완료")
                    except Exception as ex:
                        logger.warning(f"[백테스트] game_id={game.id} 예측 실패: {ex}")

                await db.commit()
            logger.info(f"[백테스트] 완료: {predicted}경기 예측, {skipped}경기 스킵")
        except Exception as exc:
            logger.error(f"[백테스트] 치명적 오류: {exc}", exc_info=True)

    _create_background_task(_run_backtest())
    return {"status": "started", "league": lg, "start": start, "end": end}


@router.post("/fix-mlb-games")
async def fix_mlb_games(
    from_date: str = Query(default=None, description="시작일 YYYY-MM-DD (기본: 오늘-7일)"),
    to_date: str = Query(default=None, description="종료일 YYYY-MM-DD (기본: 오늘+7일)"),
    db: AsyncSession = Depends(get_db),
):
    """MLB 경기의 game_time(KST), external_game_id, 선발투수, 타순을 statsapi에서 일괄 보정.
    external_game_id 없는 경기도 홈/원정팀 약어로 매칭함."""
    from datetime import date, timedelta
    from sqlalchemy import select, update
    from app.models import Game, Team
    from app.collectors.mlb_lineup_collector import fetch_mlb_lineup
    from app.pipeline.normalizer import _parse_game_time

    today = date.today()
    start = date.fromisoformat(from_date) if from_date else today - timedelta(days=7)
    end = date.fromisoformat(to_date) if to_date else today + timedelta(days=7)

    import httpx
    updated = 0
    skipped = 0

    cur = start
    while cur <= end:
        try:
            resp = httpx.get(
                "https://statsapi.mlb.com/api/v1/schedule",
                params={"sportId": 1, "date": cur.isoformat(), "hydrate": "probablePitcher"},
                timeout=15,
            )
            dates_data = resp.json().get("dates", [])
            for d in dates_data:
                for g in d.get("games", []):
                    game_type = g.get("gameType", "R")
                    if game_type not in {"R", "F", "D", "L", "W", "P"}:
                        continue

                    gid = str(g.get("gamePk", ""))
                    if not gid:
                        skipped += 1
                        continue

                    home_abbr = g["teams"]["home"]["team"].get("abbreviation", "")
                    away_abbr = g["teams"]["away"]["team"].get("abbreviation", "")
                    home_sp = g["teams"]["home"].get("probablePitcher", {}).get("fullName") or None
                    away_sp = g["teams"]["away"].get("probablePitcher", {}).get("fullName") or None
                    game_datetime = g.get("gameDate", "")  # UTC ISO: "2026-04-08T17:05:00Z"

                    # DB 경기 찾기: external_game_id 우선, 없으면 팀명 매칭
                    db_game_res = await db.execute(
                        select(Game).where(Game.external_game_id == gid, Game.league == "MLB")
                    )
                    db_game = db_game_res.scalar_one_or_none()

                    if not db_game and home_abbr and away_abbr:
                        home_team_res = await db.execute(
                            select(Team).where(Team.short_name == home_abbr, Team.league == "MLB")
                        )
                        away_team_res = await db.execute(
                            select(Team).where(Team.short_name == away_abbr, Team.league == "MLB")
                        )
                        home_t = home_team_res.scalar_one_or_none()
                        away_t = away_team_res.scalar_one_or_none()
                        if home_t and away_t:
                            fallback_res = await db.execute(
                                select(Game).where(
                                    Game.game_date == cur,
                                    Game.home_team_id == home_t.id,
                                    Game.away_team_id == away_t.id,
                                    Game.league == "MLB",
                                )
                            )
                            db_game = fallback_res.scalar_one_or_none()

                    if not db_game:
                        skipped += 1
                        continue

                    vals = {}

                    # external_game_id 복구
                    if not db_game.external_game_id:
                        vals["external_game_id"] = gid

                    # game_time + game_date 재계산 (UTC → KST, 한국 날짜로 변환)
                    if game_datetime:
                        try:
                            from dateutil import tz as _dtz
                            _dtz_UTC = _dtz.UTC
                            _dtz_KST = _dtz.gettz("Asia/Seoul")
                            from datetime import datetime as _dtt
                            dt_str = game_datetime[:19].rstrip("Z")
                            dt_utc = _dtt.fromisoformat(dt_str).replace(tzinfo=_dtz_UTC)
                            dt_kst = dt_utc.astimezone(_dtz_KST)
                            kst_date = dt_kst.date()
                            # game_date 업데이트 (ET → KST)
                            if db_game.game_date != kst_date:
                                vals["game_date"] = kst_date
                        except Exception:
                            pass
                        new_time = _parse_game_time(game_datetime[:16].rstrip("Z"), "MLB")
                        if new_time:
                            old_str = str(db_game.game_time or "")[:5]
                            new_str = str(new_time)[:5]
                            if old_str != new_str:
                                vals["game_time"] = new_time

                    # 선발투수 업데이트 (항상 최신 probable pitcher로 갱신)
                    if home_sp and db_game.home_starter_name != home_sp:
                        vals["home_starter_name"] = home_sp
                    if away_sp and db_game.away_starter_name != away_sp:
                        vals["away_starter_name"] = away_sp

                    # 타순 보완 — live feed에서 수집 (아직 없는 경우만)
                    if not db_game.home_lineup_json or not db_game.away_lineup_json:
                        lineup = await fetch_mlb_lineup(gid)
                        if lineup:
                            if lineup.get("home_lineup") and not db_game.home_lineup_json:
                                vals["home_lineup_json"] = lineup["home_lineup"]
                            if lineup.get("away_lineup") and not db_game.away_lineup_json:
                                vals["away_lineup_json"] = lineup["away_lineup"]
                            if lineup.get("home_starter") and not vals.get("home_starter_name") and not db_game.home_starter_name:
                                vals["home_starter_name"] = lineup["home_starter"]
                            if lineup.get("away_starter") and not vals.get("away_starter_name") and not db_game.away_starter_name:
                                vals["away_starter_name"] = lineup["away_starter"]

                    if vals:
                        # 선발투수가 바뀌었으면 lineup_locked 리셋 → 예측 재실행 트리거
                        if "home_starter_name" in vals or "away_starter_name" in vals:
                            vals["lineup_locked"] = False
                            vals["lineup_locked_at"] = None
                        await db.execute(update(Game).where(Game.id == db_game.id).values(**vals))
                        updated += 1
                    else:
                        skipped += 1

            await db.commit()
        except Exception as e:
            logger.warning(f"MLB 경기 보정 실패 ({cur}): {e}")
        cur += timedelta(days=1)

    return {"updated": updated, "skipped": skipped, "from": str(start), "to": str(end)}


@router.post("/fix-mlb-starters")
async def fix_mlb_starters(
    from_date: str = Query(default=None),
    to_date: str = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """fix-mlb-games로 대체됨 (하위 호환용)"""
    return await fix_mlb_games(from_date=from_date, to_date=to_date, db=db)


@router.get("/debug/games")
async def debug_games(
    target_date: str = Query(..., description="YYYY-MM-DD"),
    league: str = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """특정 날짜의 경기 목록과 game_date/game_time 확인용 디버그"""
    from sqlalchemy import select, and_
    from app.models import Game, Team

    cond = [Game.game_date == date.fromisoformat(target_date)]
    if league:
        cond.append(Game.league == league.upper())
    games = (await db.execute(select(Game).where(and_(*cond)).order_by(Game.game_time))).scalars().all()

    result = []
    for g in games:
        home = (await db.execute(select(Team).where(Team.id == g.home_team_id))).scalar_one_or_none()
        away = (await db.execute(select(Team).where(Team.id == g.away_team_id))).scalar_one_or_none()
        result.append({
            "id": g.id,
            "league": g.league,
            "game_date": str(g.game_date),
            "game_time": str(g.game_time),
            "status": g.status,
            "home": home.short_name if home else "?",
            "away": away.short_name if away else "?",
            "external_game_id": g.external_game_id,
            "home_starter": g.home_starter_name,
            "lineup_locked": g.lineup_locked,
        })
    return {"date": target_date, "count": len(result), "games": result}


@router.get("/debug/pitcher-stats")
async def debug_pitcher_stats(
    team: str = Query(default=None, description="팀 단축명 (예: 키움, KT)"),
    season: int = Query(default=2026),
    league: str = Query(default="KBO", description="KBO 또는 MLB"),
    db: AsyncSession = Depends(get_db),
):
    """DB에 저장된 투수 스탯 조회 (이름 불일치 진단용)"""
    from sqlalchemy import select, and_
    if league.upper() == "MLB":
        from app.models.mlb_stats import MlbPitcherStat as StatModel
        cond = [StatModel.season == season]
        if team:
            cond.append(StatModel.team_short == team)
        rows = (await db.execute(select(StatModel).where(and_(*cond)).order_by(StatModel.team_short, StatModel.ip.desc()))).scalars().all()
        return {"league": "MLB", "season": season, "team": team, "count": len(rows),
                "pitchers": [{"name": r.name, "team": r.team_short, "era": r.era, "ip": r.ip, "handedness": r.handedness} for r in rows]}
    else:
        from app.models.kbo_stats import KboPitcherStat as StatModel
        cond = [StatModel.season == season]
        if team:
            cond.append(StatModel.team_short == team)
        rows = (await db.execute(select(StatModel).where(and_(*cond)).order_by(StatModel.team_short, StatModel.ip.desc()))).scalars().all()
        return {"league": "KBO", "season": season, "team": team, "count": len(rows),
                "pitchers": [{"name": r.name, "team": r.team_short, "era": r.era, "ip": r.ip, "handedness": r.handedness} for r in rows]}


@router.post("/cache/flush")
async def flush_cache(pattern: str = Query(default="games:*", description="삭제할 캐시 키 패턴")):
    """Redis 캐시 삭제 (기본: games:* 전체)"""
    from app.core.redis_client import _get_redis_client, _mem_cache
    client = await _get_redis_client()
    deleted = 0
    if client:
        keys = await client.keys(pattern)
        if keys:
            deleted = await client.delete(*keys)
        await client.aclose()
    else:
        # 메모리 캐시 플러시
        import fnmatch
        to_del = [k for k in list(_mem_cache.keys()) if fnmatch.fnmatch(k, pattern)]
        for k in to_del:
            _mem_cache.pop(k, None)
        deleted = len(to_del)
    logger.info(f"캐시 삭제: {deleted}개 ({pattern})")
    return {"deleted": deleted, "pattern": pattern}
