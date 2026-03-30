"""
관리자용 수동 트리거 엔드포인트
"""
import logging
from datetime import date

from fastapi import APIRouter, Query

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/collect")
async def trigger_collect(target_date: str = Query(default=None), force: bool = Query(default=False)):
    """경기 수집 + 예측 수동 트리거. force=true면 기존 예측 삭제 후 재생성"""
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
    asyncio.create_task(run(parsed_date))
    return {"status": "started", "date": str(d), "force": force}


@router.post("/lineup")
async def trigger_lineup(target_date: str = Query(default=None)):
    """라인업 수동 수집 트리거. target_date 없으면 오늘"""
    import asyncio
    from datetime import date as date_cls, datetime

    if target_date:
        d = datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        d = date_cls.today()

    logger.info(f"수동 트리거: 라인업 수집 시작 ({d})")

    async def _run():
        from app.pipeline.lineup_watcher import run_for_date
        await run_for_date(d)
        logger.info(f"라인업 수집 완료: {d}")

    asyncio.create_task(_run())
    return {"status": "started", "date": str(d)}


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

    asyncio.create_task(_run())
    return {"status": "started", "date": str(d)}
