"""
FastAPI 앱 팩토리
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.scheduler import scheduler, setup_scheduler

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="야구 승리 예측 API",
        description="KBO/MLB 경기 승리 확률 예측 및 Claude LLM 해설 제공",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS 설정
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API 라우터 등록
    from app.api.router import api_router
    app.include_router(api_router, prefix="/api/v1")

    # 스케줄러 시작/종료 이벤트
    @app.on_event("startup")
    async def startup_event():
        setup_scheduler()
        scheduler.start()
        logger.info("앱 시작 — 스케줄러 실행 중")

        import asyncio
        asyncio.create_task(_startup_catchup())

    async def _startup_catchup():
        """시작 시 누락된 예측/결과 자동 보완"""
        import asyncio
        from datetime import date, timedelta
        from sqlalchemy import select, func  # noqa
        from app.core.database import AsyncSessionLocal
        from app.models import Game, Prediction

        await asyncio.sleep(5)  # DB 연결 안정화 대기

        today = date.today()
        yesterday = today - timedelta(days=1)

        from app.pipeline.etl_runner import ETLRunner
        from app.tasks.pre_game_predict import run as run_predict

        # 어제 결과: KBO/MLB 각각 확인 후 수집
        for league in ["KBO", "MLB"]:
            try:
                async with AsyncSessionLocal() as db:
                    yesterday_count = await db.execute(
                        select(func.count(Game.id)).where(
                            Game.game_date == yesterday,
                            Game.status == "final",
                            Game.league == league,
                        )
                    )
                    if (yesterday_count.scalar() or 0) == 0:
                        logger.info(f"시작 시 어제({yesterday}) {league} 결과 수집")
                        await ETLRunner(league=league).run_results(yesterday)
            except Exception as e:
                logger.warning(f"시작 시 {league} 결과 수집 실패: {e}")

        # 오늘 예측: KBO+MLB 통합으로 한번에
        try:
            async with AsyncSessionLocal() as db:
                today_count = await db.execute(
                    select(func.count(Prediction.id))
                    .join(Game)
                    .where(Game.game_date == today)
                )
            if (today_count.scalar() or 0) == 0:
                logger.info(f"시작 시 오늘({today}) 예측 실행")
                await run_predict()
        except Exception as e:
            logger.warning(f"시작 시 예측 실행 실패: {e}")

        # 모델 파일 없으면 자동 재학습 (Railway 재배포 후 ephemeral 파일 소실 대응)
        from app.ml.model_registry import load_latest_model
        for _auto_league in ["KBO", "MLB"]:
            _model, _ = load_latest_model(_auto_league)
            if _model is None:
                logger.warning(f"{_auto_league} 모델 파일 없음 — 자동 재학습 시작")
                async def _auto_retrain(lg=_auto_league):
                    from app.ml.trainer import Trainer
                    trainer = Trainer(league=lg)
                    await trainer.retrain()
                    logger.info(f"{lg} 자동 재학습 완료")
                import asyncio
                asyncio.create_task(_auto_retrain())

        # 향후 7일 경기 일정 수집
        from app.pipeline.etl_runner import ETLRunner
        runner = ETLRunner()
        for i in range(1, 8):
            future_date = today + timedelta(days=i)
            try:
                await runner.run_for_date(future_date)
            except Exception as e:
                logger.warning(f"향후 경기 수집 실패 ({future_date}): {e}")

    @app.on_event("shutdown")
    async def shutdown_event():
        scheduler.shutdown(wait=False)
        logger.info("앱 종료 — 스케줄러 정지")

    # 헬스체크
    @app.get("/health", tags=["시스템"])
    async def health():
        return {"status": "ok", "league": settings.league}

    return app


app = create_app()
