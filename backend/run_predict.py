"""
당일 예정 경기 예측 생성 스크립트
사용법:
  $env:LEAGUE="KBO"; $env:DATABASE_URL="..."; py -3.12 -m poetry run python run_predict.py [YYYY-MM-DD]
"""
import asyncio
import logging
import sys
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

from sqlalchemy import select
from app.config import settings
from app.core.database import AsyncSessionLocal
from app.ml.model_registry import load_latest_model
from app.ml.predictor import Predictor
from app.models import Game, Prediction


async def run(target_date: date):
    league = settings.league
    model, version = load_latest_model(league)
    if model is None:
        print(f"[{league}] 모델 없음 — 먼저 trainer.py 실행 필요")
        return
    print(f"[{league}] 모델: {model.__class__.__name__}, 버전: {version}")

    predictor = Predictor()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Game).where(
                Game.game_date == target_date,
                Game.league == league,
            )
        )
        games = result.scalars().all()

        if not games:
            print(f"{target_date} [{league}] 경기 없음")
            return

        print(f"{target_date} [{league}] {len(games)}경기 예측 시작")
        predicted = 0
        for game in games:
            # 이미 예측된 경기 건너뜀
            existing = await db.execute(
                select(Prediction).where(
                    Prediction.game_id == game.id,
                    Prediction.model_version == version,
                )
            )
            if existing.scalar_one_or_none():
                print(f"  game_id={game.id} 이미 예측됨 (버전 {version})")
                continue

            pred = await predictor.predict(game.id, db)
            if pred:
                db.add(Prediction(**pred))
                print(f"  game_id={game.id} 홈 승률 {pred['home_win_prob']:.1%} [{pred['confidence_tier']}]")
                predicted += 1
            else:
                print(f"  game_id={game.id} 예측 실패")

        await db.commit()
        print(f"완료: {predicted}경기 예측 저장")


if __name__ == "__main__":
    target = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    asyncio.run(run(target))
