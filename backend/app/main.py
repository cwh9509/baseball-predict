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
        allow_origins=settings.allowed_origins,
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
