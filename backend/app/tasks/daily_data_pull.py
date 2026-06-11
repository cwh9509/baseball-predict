"""
매일 오전 6시 실행 — 전날 경기 결과 수집 + was_correct 업데이트
"""
import logging
from datetime import date, timedelta

from app.pipeline.etl_runner import ETLRunner

logger = logging.getLogger(__name__)


async def run() -> None:
    today = date.today()
    yesterday = today - timedelta(days=1)
    logger.info(f"경기 결과 수집 시작: yesterday={yesterday}")
    for league in ["KBO", "MLB"]:
        try:
            runner = ETLRunner(league=league)
            await runner.run_results(yesterday)
            # MLB는 미국 시간대 때문에 어제+오늘 모두 확인 (KBO는 어제만)
            if league == "MLB":
                await runner.run_results(today)
            logger.info(f"{league} 경기 결과 수집 완료")
        except Exception as e:
            logger.error(f"{league} 경기 결과 수집 실패: {e}", exc_info=True)
    logger.info("경기 결과 수집 완료")


async def refresh_weather() -> None:
    """3시간마다 오늘 경기 날씨 예보 갱신 (KBO/MLB)"""
    today = date.today()
    logger.info(f"날씨 예보 갱신: {today}")
    for league in ["KBO", "MLB"]:
        try:
            await ETLRunner(league=league).run_for_date(today)
        except Exception as e:
            logger.warning(f"{league} 날씨/일정 갱신 실패: {e}")
    logger.info("날씨 예보 갱신 완료")
