"""
매일 오전 8시 실행 — 당일 예정 경기에 대한 승리 예측 생성
"""
import logging
from datetime import date

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import Game, Prediction
from app.pipeline.etl_runner import ETLRunner

logger = logging.getLogger(__name__)


async def run(target_date: date | None = None, force: bool = False) -> None:
    today = target_date or date.today()
    logger.info(f"당일 경기 예측 시작: {today}")

    # 일정 수집: 리그별로 독립적으로 체크 (KBO 있어도 MLB 수집)
    async with AsyncSessionLocal() as _db:
        for _league in ["KBO", "MLB"]:
            _existing = await _db.execute(
                select(Game).where(Game.game_date == today, Game.league == _league).limit(1)
            )
            if not _existing.scalar_one_or_none() or force:
                try:
                    runner = ETLRunner(league=_league)
                    await runner.run_for_date(today)
                except Exception as e:
                    logger.warning(f"{_league} 일정 수집 실패: {e}")

    # 예측 생성
    async with AsyncSessionLocal() as db:
        from sqlalchemy import or_
        status_filter = (
            or_(Game.status == "scheduled", Game.status == "final", Game.status == "in_progress")
            if force
            else Game.status == "scheduled"
        )
        result = await db.execute(
            select(Game).where(
                Game.game_date == today,
                status_filter,
            )
        )
        games = result.scalars().all()

        if not games:
            logger.info(f"{today}: 예측할 경기 없음")
            return

        # 예측 모델 로드
        try:
            from app.ml.predictor import Predictor
            predictor = Predictor()
        except Exception as e:
            logger.error(f"예측 모델 로드 실패: {e}")
            return

        predicted = 0
        for game in games:
            # 이미 예측된 경기 건너뜀
            existing = await db.execute(
                select(Prediction).where(
                    Prediction.game_id == game.id,
                    Prediction.model_version == predictor.model_version,
                )
            )
            if existing.scalar_one_or_none():
                continue

            try:
                result = await predictor.predict(game.id, db)
                if result:
                    db.add(Prediction(**result))
                    predicted += 1
            except Exception as e:
                logger.warning(f"게임 {game.id} 예측 실패: {e}")

        await db.commit()
    logger.info(f"예측 완료: {predicted}경기")
