"""
GET /api/v1/shap/{game_id}
피처별 SHAP 기여도 반환 — XGBoost 기반 (base model)
예측별로 어떤 피처가 승패 확률에 얼마나 기여했는지 수치화

캐싱: Redis 24시간 (예측 확정 후 변경 없음)
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import cache_get, cache_set
from app.dependencies import get_db
from app.models import Game, Prediction

router = APIRouter()
logger = logging.getLogger(__name__)


class ShapFactor(BaseModel):
    feature: str          # 피처 이름
    value: float          # 실제 피처 값
    shap_value: float     # SHAP 기여값 (양수=홈팀 유리, 음수=원정팀 유리)
    abs_impact: float     # 절대값 크기


class ShapResponse(BaseModel):
    game_id: int
    home_win_prob: float
    base_value: float                # 모델 기본값 (피처 없을 때 예측 확률)
    top_factors: list[ShapFactor]    # 상위 기여 피처 (abs_impact 내림차순)
    all_shap_values: dict[str, float]  # 전체 피처별 SHAP 값


@router.get("/{game_id}", response_model=ShapResponse)
async def get_shap(game_id: int, db: AsyncSession = Depends(get_db)):
    """예측의 피처별 SHAP 기여도 반환"""
    cache_key = f"shap:{game_id}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    # 예측 확인
    pred_result = await db.execute(
        select(Prediction)
        .where(Prediction.game_id == game_id)
        .order_by(Prediction.predicted_at.desc())
        .limit(1)
    )
    pred = pred_result.scalar_one_or_none()
    if not pred:
        raise HTTPException(status_code=404, detail="예측 데이터 없음")

    game_result = await db.execute(select(Game).where(Game.id == game_id))
    game = game_result.scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=404, detail="경기 없음")

    league = game.league

    # 피처 벡터 재계산
    try:
        from app.features.builder import build_features, get_feature_columns
        X, snapshot = await build_features(db, game_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"피처 계산 실패: {e}")

    # XGBoost 모델 로드
    try:
        xgb_model = _load_xgb_model(league)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"모델 로드 실패: {e}")

    # SHAP 계산
    try:
        import shap
        import numpy as np

        explainer = shap.TreeExplainer(xgb_model)
        shap_vals = explainer.shap_values(X.reshape(1, -1))
        base_val = float(explainer.expected_value)

        feature_cols = get_feature_columns(league)
        shap_dict = {col: float(shap_vals[0][i]) for i, col in enumerate(feature_cols)}

        # 상위 15개 피처 (abs 내림차순)
        sorted_factors = sorted(
            [
                ShapFactor(
                    feature=k,
                    value=float(snapshot.get(k, float("nan"))),
                    shap_value=v,
                    abs_impact=abs(v),
                )
                for k, v in shap_dict.items()
            ],
            key=lambda x: x.abs_impact,
            reverse=True,
        )[:15]

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SHAP 계산 실패 (shap 패키지 필요): {e}")

    result = ShapResponse(
        game_id=game_id,
        home_win_prob=float(pred.home_win_prob),
        base_value=base_val,
        top_factors=sorted_factors,
        all_shap_values=shap_dict,
    )

    await cache_set(cache_key, result.model_dump(), ttl=86400)
    return result


def _load_xgb_model(league: str):
    """XGBoost 모델 로드"""
    import xgboost as xgb
    from app.ml.model_registry import get_model_dir
    from app.config import settings

    model_dir = get_model_dir()
    lg = league.lower()
    # 최신 버전 파일 찾기
    candidates = sorted(model_dir.glob(f"xgb-{lg}-v*.ubj"), reverse=True)
    if not candidates:
        raise FileNotFoundError(f"XGBoost 모델 파일 없음 (league={league})")

    model = xgb.XGBClassifier()
    model.load_model(str(candidates[0]))
    return model
