"""
APScheduler 비동기 스케줄러
FastAPI 앱 시작(startup) 시 자동 실행, 종료(shutdown) 시 정지

스케줄:
  매일 06:00 - 전날 경기 결과 수집 + was_correct 업데이트
  매일 08:00 - 당일 경기 예측 실행
  3시간마다 - 날씨 예보 갱신
  매주 월요일 03:00 - 모델 재학습
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=settings.scheduler_timezone)


def setup_scheduler() -> None:
    """스케줄 작업 등록"""

    # 전날 결과 수집 (매일 오전 6시)
    scheduler.add_job(
        _run_daily_data_pull,
        trigger=CronTrigger(hour=6, minute=0, timezone=settings.scheduler_timezone),
        id="daily_data_pull",
        name="전날 경기 결과 수집",
        replace_existing=True,
        misfire_grace_time=3600,  # 1시간 내 실행 놓쳐도 실행
    )

    # 당일 예측 실행 (매일 오전 8시)
    scheduler.add_job(
        _run_pre_game_predict,
        trigger=CronTrigger(hour=8, minute=0, timezone=settings.scheduler_timezone),
        id="pre_game_predict",
        name="당일 경기 예측",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # 날씨 예보 갱신 (3시간마다)
    scheduler.add_job(
        _run_weather_refresh,
        trigger=CronTrigger(minute=0, hour="*/3", timezone=settings.scheduler_timezone),
        id="weather_refresh",
        name="날씨 예보 갱신",
        replace_existing=True,
    )

    # 모델 재학습 (매주 월요일 오전 3시)
    scheduler.add_job(
        _run_model_retrain,
        trigger=CronTrigger(day_of_week="mon", hour=3, minute=0, timezone=settings.scheduler_timezone),
        id="model_retrain",
        name="주간 모델 재학습",
        replace_existing=True,
    )

    # KBO 라인업 감시
    # 주말(토·일): 14:00 시작 → 12:00~15:30 체크
    # 평일(월~금): 18:30 시작 → 16:00~19:30 체크
    # → 12:00~19:30 30분 간격으로 커버 (불필요한 호출은 DB 조회 후 즉시 종료)
    scheduler.add_job(
        _run_lineup_watch,
        trigger=CronTrigger(
            hour="12-19", minute="0,30",
            timezone=settings.scheduler_timezone
        ),
        id="lineup_watch",
        name="KBO 라인업 감시",
        replace_existing=True,
    )

    logger.info("스케줄러 작업 등록 완료 (5개 작업)")


async def _run_daily_data_pull() -> None:
    try:
        from app.tasks.daily_data_pull import run
        await run()
    except Exception as e:
        logger.error(f"daily_data_pull 실패: {e}", exc_info=True)


async def _run_pre_game_predict() -> None:
    try:
        from app.tasks.pre_game_predict import run
        await run()
    except Exception as e:
        logger.error(f"pre_game_predict 실패: {e}", exc_info=True)


async def _run_weather_refresh() -> None:
    try:
        from app.tasks.daily_data_pull import refresh_weather
        await refresh_weather()
    except Exception as e:
        logger.error(f"weather_refresh 실패: {e}", exc_info=True)


async def _run_model_retrain() -> None:
    try:
        from app.tasks.model_retrain import run
        await run()
    except Exception as e:
        logger.error(f"model_retrain 실패: {e}", exc_info=True)


async def _run_lineup_watch() -> None:
    try:
        from app.pipeline.lineup_watcher import run
        await run()
    except Exception as e:
        logger.error(f"lineup_watch 실패: {e}", exc_info=True)
