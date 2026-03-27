"""
GET /api/v1/predict/{game_id}
전체 예측 결과 + 피처 스냅샷 + LLM 해설 반환
LLM 해설은 지연 생성 (이 엔드포인트 조회 시 Claude API 호출)
Redis 캐시: TTL 1800초
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import cache_get, cache_set
from app.dependencies import get_db
from app.models import Game, Prediction, Team
from app.schemas.prediction import ExplanationSchema, KeyFactor, LineupEntrySchema, LineupSchema, PredictionDetailResponse

router = APIRouter()


@router.get("/{game_id}", response_model=PredictionDetailResponse)
async def get_prediction(
    game_id: int,
    db: AsyncSession = Depends(get_db),
):
    cache_key = f"prediction:{game_id}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    # 예측 조회
    pred_result = await db.execute(
        select(Prediction)
        .where(Prediction.game_id == game_id)
        .order_by(Prediction.predicted_at.desc())
        .limit(1)
    )
    pred = pred_result.scalar_one_or_none()
    if not pred:
        raise HTTPException(status_code=404, detail="예측 데이터가 없습니다")

    # 경기 및 팀 조회
    game_result = await db.execute(select(Game).where(Game.id == game_id))
    game = game_result.scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=404, detail="경기를 찾을 수 없습니다")

    winner_result = await db.execute(select(Team).where(Team.id == pred.predicted_winner_id))
    winner = winner_result.scalar_one_or_none()

    home_result = await db.execute(select(Team).where(Team.id == game.home_team_id))
    home_team = home_result.scalar_one_or_none()
    away_result = await db.execute(select(Team).where(Team.id == game.away_team_id))
    away_team = away_result.scalar_one_or_none()

    # LLM 해설 지연 생성
    explanation = None
    if pred.llm_explanation:
        import json
        try:
            raw = json.loads(pred.llm_explanation)
            explanation = ExplanationSchema(
                summary=raw["summary"],
                key_factors=[KeyFactor(**f) for f in raw.get("key_factors", [])],
                confidence_note=raw.get("confidence_note", ""),
            )
        except Exception:
            pass
    else:
        # 아직 해설이 없으면 지금 생성
        explanation = await _generate_explanation_lazy(pred, game, home_team, away_team, db)

    # 라인업 데이터
    lineup = None
    if game.home_lineup_json or game.away_lineup_json or game.home_starter_name or game.away_starter_name:
        lineup = LineupSchema(
            home_starter=game.home_starter_name,
            away_starter=game.away_starter_name,
            home_lineup=[LineupEntrySchema(**e) for e in (game.home_lineup_json or [])],
            away_lineup=[LineupEntrySchema(**e) for e in (game.away_lineup_json or [])],
            lineup_locked=bool(game.lineup_locked),
        )

    home_win_prob = float(pred.home_win_prob)
    response = PredictionDetailResponse(
        game_id=game_id,
        game_date=game.game_date.isoformat() if game.game_date else None,
        home_team={"id": home_team.id, "name": home_team.name, "short_name": home_team.short_name} if home_team else None,
        away_team={"id": away_team.id, "name": away_team.name, "short_name": away_team.short_name} if away_team else None,
        model_version=pred.model_version,
        predicted_at=pred.predicted_at,
        home_win_prob=home_win_prob,
        away_win_prob=round(1.0 - home_win_prob, 4),
        predicted_winner={"id": winner.id, "name": winner.name} if winner else {},
        confidence_tier=pred.confidence_tier,
        feature_snapshot=pred.feature_snapshot or {},
        explanation=explanation,
        lineup=lineup,
    )

    # explanation 없으면 캐시 저장 안 함 (다음 요청에서 재시도)
    if explanation is not None:
        await cache_set(cache_key, response.model_dump(mode="json"), ttl=1800)
    return response


async def _generate_explanation_lazy(pred, game, home_team, away_team, db):
    """LLM 해설 지연 생성 후 DB 저장"""
    import json
    from datetime import datetime, timezone

    try:
        from app.llm.explainer import Explainer
        explainer = Explainer()
        result = await explainer.generate(
            prediction_id=pred.id,
            home_team=home_team.name if home_team else "홈팀",
            away_team=away_team.name if away_team else "원정팀",
            game_date=str(game.game_date),
            home_win_prob=float(pred.home_win_prob),
            predicted_winner=home_team.name if float(pred.home_win_prob) >= 0.5 else (away_team.name if away_team else "원정팀"),
            confidence_tier=pred.confidence_tier,
            snapshot=pred.feature_snapshot or {},
        )
        if result:
            # DB 업데이트
            pred.llm_explanation = json.dumps(result, ensure_ascii=False)
            pred.llm_model = "claude-sonnet-4-6"
            pred.llm_generated_at = datetime.now(timezone.utc)
            await db.flush()

            from app.schemas.prediction import ExplanationSchema, KeyFactor
            return ExplanationSchema(
                summary=result["summary"],
                key_factors=[KeyFactor(**f) for f in result.get("key_factors", [])],
                confidence_note=result.get("confidence_note", ""),
            )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"LLM 해설 지연 생성 실패: {e}")
    return None
