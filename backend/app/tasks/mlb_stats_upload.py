"""
주간 MLB 스탯 자동 수집 태스크 (스케줄러 내부 실행용)
매주 일요일 오전 2시 실행 — 월요일 재학습(03:00) 전 데이터 최신화

수집 내용:
  - 투수 개인 스탯 (ERA, FIP, WHIP, K/9, 구종, 구속, 홈/원정 ERA, 최근 3경기 ERA)
  - 팀 불펜 집계
  - 팀 타선 집계 + vs LHP/RHP 스플릿
"""
import logging
from datetime import date

logger = logging.getLogger(__name__)


async def run(season: int | None = None) -> None:
    """스케줄러에서 호출되는 진입점"""
    s = season or date.today().year
    logger.info(f"[mlb_stats_upload] season={s} 수집 시작")

    try:
        from app.collectors.mlb_stats_collector import upsert_mlb_stats
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            summary = await upsert_mlb_stats(s, db)
        logger.info(f"[mlb_stats_upload] 완료: {summary}")
    except Exception as e:
        logger.error(f"[mlb_stats_upload] 실패: {e}", exc_info=True)
