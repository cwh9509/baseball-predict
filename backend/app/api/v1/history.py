"""
GET /api/v1/history
신뢰도 등급별 적중률 요약 + 페이지네이션된 예측 히스토리
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Integer, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models import Game, Prediction, Team

router = APIRouter()


@router.get("")
async def get_history(
    league: str = Query(..., description="KBO 또는 MLB"),
    from_date: Optional[str] = Query(None, description="시작 날짜 YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, description="종료 날짜 YYYY-MM-DD"),
    model_ver: Optional[str] = Query(None, description="모델 버전 필터"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    # 날짜 파싱
    start = date.fromisoformat(from_date) if from_date else date(date.today().year, 1, 1)
    end = date.fromisoformat(to_date) if to_date else date.today()

    # 필터 조건
    conditions = [
        Game.game_date >= start,
        Game.game_date <= end,
        Game.league == league,
        Prediction.was_correct.isnot(None),
    ]
    if model_ver:
        conditions.append(Prediction.model_version == model_ver)

    # 전체 개수
    count_stmt = (
        select(func.count(Prediction.id))
        .join(Game, Prediction.game_id == Game.id)
        .where(and_(*conditions))
    )
    total = (await db.execute(count_stmt)).scalar() or 0

    # 정확도 요약
    summary_stmt = (
        select(
            Prediction.confidence_tier,
            func.count(Prediction.id).label("total"),
            func.sum(func.cast(Prediction.was_correct, Integer)).label("correct"),
        )
        .join(Game, Prediction.game_id == Game.id)
        .where(and_(*conditions))
        .group_by(Prediction.confidence_tier)
    )
    summary_rows = (await db.execute(summary_stmt)).all()

    by_confidence = {}
    total_correct = 0
    for row in summary_rows:
        tier_total = row.total or 0
        tier_correct = row.correct or 0
        total_correct += tier_correct
        by_confidence[row.confidence_tier] = {
            "total": tier_total,
            "accuracy": round(tier_correct / tier_total, 4) if tier_total > 0 else 0.0,
        }

    overall_accuracy = round(total_correct / total, 4) if total > 0 else 0.0

    # 페이지네이션 쿼리
    offset = (page - 1) * per_page
    items_stmt = (
        select(Prediction, Game)
        .join(Game, Prediction.game_id == Game.id)
        .where(and_(*conditions))
        .order_by(Game.game_date.desc())
        .offset(offset)
        .limit(per_page)
    )
    rows = (await db.execute(items_stmt)).all()

    predictions = []
    for pred, game in rows:
        home_team = (await db.execute(select(Team).where(Team.id == game.home_team_id))).scalar_one_or_none()
        away_team = (await db.execute(select(Team).where(Team.id == game.away_team_id))).scalar_one_or_none()
        winner_team = (await db.execute(select(Team).where(Team.id == pred.predicted_winner_id))).scalar_one_or_none() if pred.predicted_winner_id else None
        actual_winner = (await db.execute(select(Team).where(Team.id == game.winner_team_id))).scalar_one_or_none() if game.winner_team_id else None

        predictions.append({
            "game_id": game.id,
            "game_date": str(game.game_date),
            "matchup": f"{home_team.name if home_team else '?'} vs {away_team.name if away_team else '?'}",
            "predicted_winner": winner_team.name if winner_team else "알 수 없음",
            "actual_winner": actual_winner.name if actual_winner else None,
            "home_win_prob": float(pred.home_win_prob),
            "was_correct": pred.was_correct,
            "confidence_tier": pred.confidence_tier,
        })

    return {
        "summary": {
            "total_predictions": total,
            "correct": total_correct,
            "accuracy": overall_accuracy,
            "by_confidence": by_confidence,
        },
        "predictions": predictions,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": (total + per_page - 1) // per_page,
        },
    }
