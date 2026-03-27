"""API 라우터 통합"""
from fastapi import APIRouter

from app.api.v1 import games, history, lineup, predictions, teams

api_router = APIRouter()

api_router.include_router(games.router, prefix="/games", tags=["경기"])
api_router.include_router(predictions.router, prefix="/predict", tags=["예측"])
api_router.include_router(teams.router, prefix="/team", tags=["팀"])
api_router.include_router(history.router, prefix="/history", tags=["히스토리"])
api_router.include_router(lineup.router, prefix="/games", tags=["라인업"])
