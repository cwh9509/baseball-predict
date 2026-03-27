"""
매주 월요일 오전 3시 실행 — 최근 2시즌 데이터로 모델 재학습
"""
import logging

logger = logging.getLogger(__name__)


async def run() -> None:
    logger.info("주간 모델 재학습 시작")
    try:
        from app.ml.trainer import Trainer
        trainer = Trainer()
        await trainer.retrain()
        logger.info("모델 재학습 완료")
    except Exception as e:
        logger.error(f"모델 재학습 실패: {e}", exc_info=True)
