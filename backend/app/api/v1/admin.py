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
async def trigger_collect(target_date: str = Query(default=None), force: bool = Query(default=False), league: str = Query(default=None)):
    """경기 수집 + 예측 수동 트리거. force=true면 기존 예측 삭제 후 재생성. league=MLB로 특정 리그만 수집 가능"""
    from app.tasks.pre_game_predict import run
    import asyncio
    from datetime import datetime

    parsed_date = datetime.strptime(target_date, "%Y-%m-%d").date() if target_date else None
    d = parsed_date or date.today()

    if force:
        from sqlalchemy import delete
        from app.core.database import AsyncSessionLocal
        from app.models import Game, Prediction
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            games = (await db.execute(select(Game).where(Game.game_date == d))).scalars().all()
            for game in games:
                await db.execute(delete(Prediction).where(Prediction.game_id == game.id))
            await db.commit()
        logger.info(f"기존 예측 삭제 완료: {d}")

    logger.info(f"수동 트리거: 경기 수집 + 예측 시작 ({d})")
    _create_background_task(run(parsed_date, force=force))
    return {"status": "started", "date": str(d), "force": force}


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
    """statiz 스탯 수집 + DB 업로드 수동 트리거"""
    import asyncio
    from datetime import date as date_cls

    s = season or date_cls.today().year
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
async def trigger_collect_results(target_date: str = Query(default=None)):
    """전날 경기 결과 수집 수동 트리거"""
    import asyncio
    from datetime import datetime, timedelta
    from app.pipeline.etl_runner import ETLRunner

    if target_date:
        d = datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        from datetime import date as date_cls
        d = date_cls.today() - timedelta(days=1)

    logger.info(f"수동 트리거: 경기 결과 수집 시작 ({d})")

    async def _run():
        runner = ETLRunner()
        await runner.run_results(d)
        logger.info(f"경기 결과 수집 완료: {d}")

    _create_background_task(_run())
    return {"status": "started", "date": str(d)}


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
