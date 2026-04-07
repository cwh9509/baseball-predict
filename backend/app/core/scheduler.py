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

    # KBO 스탯 수집 + 업로드 (매주 월요일 오전 2시 30분 — 재학습 30분 전)
    scheduler.add_job(
        _run_weekly_stats_upload,
        trigger=CronTrigger(day_of_week="mon", hour=2, minute=30, timezone=settings.scheduler_timezone),
        id="weekly_stats_upload",
        name="주간 KBO 스탯 수집",
        replace_existing=True,
    )

    # MLB 스탯 수집 (매주 일요일 오전 2시 — KBO 수집보다 먼저, 재학습 전날)
    scheduler.add_job(
        _run_weekly_mlb_stats_upload,
        trigger=CronTrigger(day_of_week="sun", hour=2, minute=0, timezone=settings.scheduler_timezone),
        id="weekly_mlb_stats_upload",
        name="주간 MLB 스탯 수집",
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

    # KBO 라인업 감시 (30분 간격, 광역)
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

    # KBO 경기 시작 30분 전 집중 감시 (10분 간격)
    scheduler.add_job(
        _run_lineup_watch_pre_game,
        trigger=CronTrigger(
            hour="12-20", minute="*/10",
            timezone=settings.scheduler_timezone
        ),
        id="lineup_watch_pre_game",
        name="KBO 라인업 경기 전 집중 감시",
        replace_existing=True,
    )

    # MLB 라인업 감시 (30분 간격, 미국 동부 오전 9시~오후 11시 = ET 기준)
    # scheduler_timezone이 America/New_York이면 MLB 경기 시간대와 맞음
    scheduler.add_job(
        _run_mlb_lineup_watch,
        trigger=CronTrigger(
            hour="9-23", minute="0,30",
            timezone=settings.scheduler_timezone
        ),
        id="mlb_lineup_watch",
        name="MLB 라인업 감시",
        replace_existing=True,
    )

    # MLB 내일 경기 미리 수집 (ET 15:00 = KST 00:00)
    # 한국 유저가 자정 이후 앱에서 다음날 MLB 경기/예측 바로 볼 수 있게
    scheduler.add_job(
        _run_mlb_next_day_collect,
        trigger=CronTrigger(hour=15, minute=0, timezone=settings.scheduler_timezone),
        id="mlb_next_day_collect",
        name="MLB 익일 경기 수집 (KST 자정)",
        replace_existing=True,
    )

    logger.info("스케줄러 작업 등록 완료 (10개 작업)")


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


async def _run_weekly_stats_upload() -> None:
    """statiz에서 KBO 스탯 스크래핑 후 DB 업로드 + 스플릿 계산"""
    try:
        from datetime import date
        from app.tasks.stats_upload import run as run_stats_upload
        from app.tasks.compute_splits import run as run_splits
        season = date.today().year
        await run_stats_upload(season=season)
        await run_splits(season=season)
    except Exception as e:
        logger.error(f"weekly_stats_upload 실패: {e}", exc_info=True)


async def _run_weekly_mlb_stats_upload() -> None:
    try:
        from app.tasks.mlb_stats_upload import run as run_mlb
        await run_mlb()
    except Exception as e:
        logger.error(f"weekly_mlb_stats_upload 실패: {e}", exc_info=True)


async def _run_lineup_watch() -> None:
    try:
        from app.pipeline.lineup_watcher import run
        await run()
    except Exception as e:
        logger.error(f"lineup_watch 실패: {e}", exc_info=True)


async def _run_lineup_watch_pre_game() -> None:
    try:
        from app.pipeline.lineup_watcher import run_pre_game
        await run_pre_game()
    except Exception as e:
        logger.error(f"lineup_watch_pre_game 실패: {e}", exc_info=True)


async def _run_mlb_next_day_collect() -> None:
    """ET 15:00 (= KST 00:00) — 다음 ET 날짜 MLB 경기 미리 수집 + 예측"""
    try:
        from datetime import date, timedelta
        from app.pipeline.etl_runner import ETLRunner
        from app.tasks.pre_game_predict import run as predict_run

        tomorrow_et = date.today() + timedelta(days=1)
        logger.info(f"MLB 익일 경기 수집 시작: {tomorrow_et}")
        runner = ETLRunner(league="MLB")
        await runner.run_for_date(tomorrow_et)
        await predict_run(target_date=tomorrow_et)
        logger.info(f"MLB 익일 경기 수집 + 예측 완료: {tomorrow_et}")
    except Exception as e:
        logger.error(f"mlb_next_day_collect 실패: {e}", exc_info=True)


async def _run_mlb_lineup_watch() -> None:
    try:
        from app.pipeline.lineup_watcher import run_mlb
        await run_mlb()
    except Exception as e:
        logger.error(f"mlb_lineup_watch 실패: {e}", exc_info=True)
