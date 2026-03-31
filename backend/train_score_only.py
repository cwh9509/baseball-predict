"""
스코어 회귀 모델만 단독 학습
Usage: python train_score_only.py
"""
import asyncio
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main():
    from app.ml.trainer import Trainer
    trainer = Trainer()

    logger.info("스코어 회귀 학습 데이터 수집 중...")
    X, y_home, y_away = await trainer._collect_score_training_data()

    if len(X) < 50:
        logger.error(f"학습 데이터 부족: {len(X)}경기 (최소 50경기 필요)")
        return

    logger.info(f"학습 데이터: {len(X)}경기 — 모델 학습 시작")
    version = datetime.now().strftime("%Y%m%d")
    trainer._train_score_models(X, y_home, y_away, version)
    logger.info("스코어 모델 학습 완료!")


if __name__ == "__main__":
    asyncio.run(main())
