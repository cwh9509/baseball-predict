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


@router.post("/collect-results")
async def trigger_collect_results():
    """전날 경기 결과 수집 수동 트리거"""
    from app.tasks.daily_data_pull import run
    import asyncio

    logger.info("수동 트리거: 전날 결과 수집 시작")
    asyncio.create_task(run())
    return {"status": "started"}
