"""
매일 오전 8시 실행 — 예정 경기 일정 수집 + 승리 예측 생성
- KBO: 당일
- MLB: 당일 ~ 7일 후 (KBO처럼 매일 공통 작업에서 자동 유지)
"""
import logging
from datetime import date, timedelta

from sqlalchemy import or_, select

from app.core.database import AsyncSessionLocal
from app.models import Game, Prediction
from app.pipeline.etl_runner import ETLRunner

logger = logging.getLogger(__name__)

MLB_FUTURE_DAYS = 7


def _dates_for_league(league: str, anchor: date, *, single_date: bool) -> list[date]:
    """리그별 수집/예측 대상 날짜 목록"""
    if single_date:
        return [anchor]
    if league == "MLB":
        return [anchor + timedelta(days=i) for i in range(MLB_FUTURE_DAYS + 1)]
    return [anchor]


async def run(target_date: date | None = None, force: bool = False) -> None:
    anchor = target_date or date.today()
    single_date = target_date is not None
    logger.info(
        "경기 일정 수집/예측 시작: anchor=%s single_date=%s force=%s",
        anchor,
        single_date,
        force,
    )

    # 1) 일정 수집 (리그·날짜별 — 없을 때만, force면 항상)
    async with AsyncSessionLocal() as _db:
        for league in ["KBO", "MLB"]:
            for d in _dates_for_league(league, anchor, single_date=single_date):
                existing = await _db.execute(
                    select(Game).where(Game.game_date == d, Game.league == league).limit(1)
                )
                if not existing.scalar_one_or_none() or force:
                    try:
                        await ETLRunner(league=league).run_for_date(d)
                    except Exception as e:
                        logger.warning(f"{league} 일정 수집 실패 ({d}): {e}")

    # 2) 예측 생성
    status_filter = (
        or_(Game.status == "scheduled", Game.status == "final", Game.status == "in_progress")
        if force
        else Game.status == "scheduled"
    )

    try:
        from app.ml.predictor import Predictor
        predictor = Predictor()
    except Exception as e:
        logger.error(f"예측 모델 로드 실패: {e}")
        return

    total_predicted = 0
    flush_dates: set[tuple[str, str]] = set()

    async with AsyncSessionLocal() as db:
        for league in ["KBO", "MLB"]:
            for d in _dates_for_league(league, anchor, single_date=single_date):
                result = await db.execute(
                    select(Game).where(
                        Game.game_date == d,
                        Game.league == league,
                        status_filter,
                    )
                )
                games = result.scalars().all()
                if not games:
                    continue

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
                        pred_result = await predictor.predict(game.id, db)
                        if pred_result:
                            db.add(Prediction(**pred_result))
                            predicted += 1
                    except Exception as e:
                        logger.warning(f"게임 {game.id} 예측 실패: {e}")

                if predicted:
                    await db.commit()
                    total_predicted += predicted
                    flush_dates.add((league, d.isoformat()))
                    logger.info(f"{league} {d}: {predicted}경기 예측 생성")

    logger.info(f"예측 완료: 총 {total_predicted}경기")

    # 캐시 플러시
    try:
        from app.core.redis_client import cache_delete
        if flush_dates:
            for league, d_str in flush_dates:
                await cache_delete(f"games:today:{league}:{d_str}")
        else:
            for league in ["KBO", "MLB"]:
                for d in _dates_for_league(league, anchor, single_date=single_date):
                    await cache_delete(f"games:today:{league}:{d.isoformat()}")
    except Exception as e:
        logger.warning(f"캐시 플러시 실패: {e}")
