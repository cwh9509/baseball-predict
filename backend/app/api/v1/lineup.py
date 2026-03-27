"""
POST /api/v1/games/{game_id}/lineup
라인업 수동 트리거 또는 직접 업데이트 엔드포인트

사용 시나리오:
  1. 수동 트리거: body 없이 POST → KBO 웹사이트에서 자동 수집
  2. 직접 입력:   body에 lineup 데이터 → DB에 직접 저장 (admin용)

인증: X-Admin-Key 헤더 (settings.admin_api_key)
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.redis_client import cache_delete
from app.dependencies import get_db
from app.models import Game

logger = logging.getLogger(__name__)
router = APIRouter()


class LineupEntry(BaseModel):
    order: int
    name: str
    position: str = ""


class LineupUpdateRequest(BaseModel):
    home_starter: Optional[str] = None
    away_starter: Optional[str] = None
    home_lineup: Optional[list[LineupEntry]] = None
    away_lineup: Optional[list[LineupEntry]] = None


class LineupUpdateResponse(BaseModel):
    game_id: int
    updated: bool
    home_starter: Optional[str]
    away_starter: Optional[str]
    home_lineup_count: int
    away_lineup_count: int
    prediction_retriggered: bool


def _check_admin_key(x_admin_key: Optional[str] = Header(None)) -> None:
    """간단한 API 키 인증"""
    admin_key = getattr(settings, "admin_api_key", "")
    if admin_key and x_admin_key != admin_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="유효하지 않은 admin key",
        )


@router.post("/{game_id}/lineup", response_model=LineupUpdateResponse)
async def update_lineup(
    game_id: int,
    body: Optional[LineupUpdateRequest] = None,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_check_admin_key),
):
    """
    라인업 업데이트 + 예측 재실행

    - body 없음 또는 빈 body: KBO 웹사이트에서 자동 수집 시도
    - body 있음: 직접 입력 데이터로 업데이트
    """
    # 게임 존재 확인
    game_result = await db.execute(select(Game).where(Game.id == game_id))
    game = game_result.scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=404, detail=f"game_id={game_id} 없음")

    if game.status == "final":
        raise HTTPException(status_code=400, detail="이미 종료된 경기")

    lineup_data = None

    if body and (body.home_starter or body.away_starter or body.home_lineup or body.away_lineup):
        # 직접 입력
        lineup_data = {
            "home_starter": body.home_starter,
            "away_starter": body.away_starter,
            "home_lineup": [e.model_dump() for e in body.home_lineup] if body.home_lineup else [],
            "away_lineup": [e.model_dump() for e in body.away_lineup] if body.away_lineup else [],
            "source": "manual",
        }
    elif game.league == "KBO" and game.external_game_id:
        # 자동 수집 시도
        from app.collectors.lineup_collector import KBOLineupCollector
        collector = KBOLineupCollector()
        lineup_data = await collector.fetch_lineup(game.external_game_id)
        if not lineup_data:
            raise HTTPException(
                status_code=404,
                detail="라인업 미발표 또는 수집 실패 (경기 시작 1~2시간 전에 재시도)",
            )
    else:
        raise HTTPException(status_code=400, detail="KBO 이외 리그는 body에 라인업 직접 입력 필요")

    # DB 업데이트
    now = datetime.now(timezone.utc)
    updates: dict = {"updated_at": now}

    if lineup_data.get("home_starter"):
        updates["home_starter_name"] = lineup_data["home_starter"]
    if lineup_data.get("away_starter"):
        updates["away_starter_name"] = lineup_data["away_starter"]
    if lineup_data.get("home_lineup"):
        updates["home_lineup_json"] = lineup_data["home_lineup"]
    if lineup_data.get("away_lineup"):
        updates["away_lineup_json"] = lineup_data["away_lineup"]

    home_lineup_list = lineup_data.get("home_lineup") or []
    away_lineup_list = lineup_data.get("away_lineup") or []
    if home_lineup_list and away_lineup_list:
        updates["lineup_locked"] = True
        updates["lineup_locked_at"] = now

    await db.execute(update(Game).where(Game.id == game_id).values(**updates))
    await db.commit()

    # 예측 재실행
    prediction_done = False
    try:
        from app.pipeline.lineup_watcher import _retrigger_prediction
        await _retrigger_prediction(db, game_id)
        prediction_done = True
    except Exception as e:
        logger.warning(f"game_id={game_id} 예측 재실행 실패: {e}")

    # 관련 캐시 무효화
    try:
        today_str = game.game_date.isoformat()
        await cache_delete(f"games:today:{game.league}:{today_str}")
        await cache_delete(f"predict:{game_id}")
    except Exception:
        pass

    return LineupUpdateResponse(
        game_id=game_id,
        updated=True,
        home_starter=lineup_data.get("home_starter"),
        away_starter=lineup_data.get("away_starter"),
        home_lineup_count=len(home_lineup_list),
        away_lineup_count=len(away_lineup_list),
        prediction_retriggered=prediction_done,
    )
