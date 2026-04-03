"""
GET /api/v1/history        - 페이지네이션된 예측 히스토리 + 요약
GET /api/v1/history/calendar - 월별 달력 뷰 (일별 적중 현황)
GET /api/v1/history/teams    - 팀별 예측 정확도
GET /api/v1/history/betting  - 베팅 시뮬레이터용 전체 데이터 (오래된순)
"""
from calendar import monthrange
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

    # 게임당 최신 예측 1개 기준 서브쿼리
    latest_subq = (
        select(func.max(Prediction.id).label("max_id"))
        .join(Game, Prediction.game_id == Game.id)
        .where(and_(*conditions))
        .group_by(Prediction.game_id)
    ).subquery()

    # 전체 개수 (게임 수 기준)
    count_stmt = (
        select(func.count(Prediction.id))
        .where(Prediction.id.in_(select(latest_subq.c.max_id)))
    )
    total = (await db.execute(count_stmt)).scalar() or 0

    # 정확도 요약 (최신 예측 기준)
    summary_stmt = (
        select(
            Prediction.confidence_tier,
            func.count(Prediction.id).label("total"),
            func.sum(func.cast(Prediction.was_correct, Integer)).label("correct"),
        )
        .where(Prediction.id.in_(select(latest_subq.c.max_id)))
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
        .where(Prediction.id.in_(select(latest_subq.c.max_id)))
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

        home_win_prob = float(pred.home_win_prob)
        if pred.predicted_winner_id == game.home_team_id:
            predicted_win_prob = home_win_prob
        else:
            predicted_win_prob = 1.0 - home_win_prob

        predictions.append({
            "game_id": game.id,
            "game_date": str(game.game_date),
            "matchup": f"{home_team.name if home_team else '?'} vs {away_team.name if away_team else '?'}",
            "predicted_winner": winner_team.name if winner_team else "알 수 없음",
            "actual_winner": actual_winner.name if actual_winner else None,
            "home_win_prob": home_win_prob,
            "predicted_win_prob": predicted_win_prob,
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


def _latest_pred_subq(conditions):
    """game_id별 최신 prediction id 서브쿼리"""
    return (
        select(func.max(Prediction.id).label("max_id"))
        .join(Game, Prediction.game_id == Game.id)
        .where(and_(*conditions))
        .group_by(Prediction.game_id)
    ).subquery()


@router.get("/calendar")
async def get_history_calendar(
    league: str = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """월별 달력: 날짜별 예측 총수 + 적중수 반환"""
    start = date(year, month, 1)
    _, last_day = monthrange(year, month)
    end = date(year, month, last_day)

    conditions = [
        Game.game_date >= start,
        Game.game_date <= end,
        Game.league == league,
        Prediction.was_correct.isnot(None),
    ]

    subq = _latest_pred_subq(conditions)
    stmt = (
        select(
            Game.game_date,
            func.count(Prediction.id).label("total"),
            func.sum(func.cast(Prediction.was_correct, Integer)).label("correct"),
        )
        .join(Game, Prediction.game_id == Game.id)
        .where(Prediction.id.in_(select(subq.c.max_id)))
        .group_by(Game.game_date)
    )
    rows = (await db.execute(stmt)).all()

    days: dict = {}
    for row in rows:
        days[str(row.game_date)] = {
            "total": row.total or 0,
            "correct": int(row.correct or 0),
        }
    return {"year": year, "month": month, "days": days}


@router.get("/teams")
async def get_history_teams(
    league: str = Query(...),
    year: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """팀별 예측 정확도 집계"""
    start = date(year, 1, 1)
    end = date(year, 12, 31)

    conditions = [
        Game.game_date >= start,
        Game.game_date <= end,
        Game.league == league,
        Prediction.was_correct.isnot(None),
    ]

    subq = _latest_pred_subq(conditions)
    stmt = (
        select(Prediction, Game)
        .join(Game, Prediction.game_id == Game.id)
        .where(Prediction.id.in_(select(subq.c.max_id)))
    )
    rows = (await db.execute(stmt)).all()

    # 팀별 집계 (홈/어웨이 모두 카운트)
    team_stats: dict = {}  # team_id -> {total, correct}
    for pred, game in rows:
        for team_id in [game.home_team_id, game.away_team_id]:
            if team_id not in team_stats:
                team_stats[team_id] = {"total": 0, "correct": 0}
            team_stats[team_id]["total"] += 1
            if pred.was_correct:
                team_stats[team_id]["correct"] += 1

    result = []
    for team_id, stats in team_stats.items():
        team = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
        if not team:
            continue
        t = stats["total"]
        c = stats["correct"]
        result.append({
            "team_id": team_id,
            "team_name": team.name,
            "team_short": team.short_name,
            "total": t,
            "correct": c,
            "accuracy": round(c / t, 4) if t > 0 else 0.0,
        })

    result.sort(key=lambda x: x["accuracy"], reverse=True)
    return {"teams": result, "year": year}


@router.get("/betting")
async def get_history_betting(
    league: str = Query(...),
    year: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """베팅 시뮬레이터: 오래된순 전체 예측 + 예측 확률 반환"""
    start = date(year, 1, 1)
    end = date(year, 12, 31)

    conditions = [
        Game.game_date >= start,
        Game.game_date <= end,
        Game.league == league,
        Prediction.was_correct.isnot(None),
    ]

    subq = _latest_pred_subq(conditions)
    stmt = (
        select(Prediction, Game)
        .join(Game, Prediction.game_id == Game.id)
        .where(Prediction.id.in_(select(subq.c.max_id)))
        .order_by(Game.game_date.asc())
    )
    rows = (await db.execute(stmt)).all()

    bets = []
    for pred, game in rows:
        home_win_prob = float(pred.home_win_prob)
        predicted_win_prob = (
            home_win_prob if pred.predicted_winner_id == game.home_team_id
            else 1.0 - home_win_prob
        )
        bets.append({
            "game_date": str(game.game_date),
            "game_id": game.id,
            "predicted_win_prob": round(predicted_win_prob, 4),
            "was_correct": pred.was_correct,
            "confidence_tier": pred.confidence_tier,
        })

    return {"bets": bets, "year": year}
