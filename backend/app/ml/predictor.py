"""
ML 예측 실행기
- XGBoost + LightGBM + CatBoost + Stacking 앙상블
- 메타 모델 없으면 단순 평균 폴백
- 단일 모델만 있어도 정상 동작
"""
import logging
from typing import Optional

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.builder import build_features
from app.ml.model_registry import load_latest_model, load_ensemble_models, load_score_models

logger = logging.getLogger(__name__)


def assign_confidence_tier(home_win_prob: float) -> str:
    """
    홈 승률 기반 신뢰도 등급 부여
    high:   > 68% 또는 < 32%
    medium: 58~68% 또는 32~42%
    low:    42~58%
    """
    distance = abs(home_win_prob - 0.5)
    if distance > 0.18:
        return "high"
    elif distance > 0.08:
        return "medium"
    else:
        return "low"


class Predictor:

    def __init__(self, league: Optional[str] = None):
        self._league = league
        # league → (xgb_model, lgb_model, cat_model, meta_model, version)
        self._ensemble: dict[str, tuple] = {}
        # league → (home_score_model, away_score_model, version)
        self._score_models: dict[str, tuple] = {}
        self._load_models(self._league)

    def _load_models(self, league: Optional[str] = None):
        lg_key = league or "default"
        xgb_model, lgb_model, cat_model, meta_model, version = load_ensemble_models(league)

        # 앙상블 로드 실패 시 단일 모델 폴백
        if xgb_model is None and lgb_model is None and cat_model is None:
            single, single_ver = load_latest_model(league)
            if single is not None:
                xgb_model = single
                version = single_ver
                logger.info(f"[{lg_key}] 단일 모델 로드: v{version}")
            else:
                logger.warning(f"[{lg_key}] 저장된 모델 없음 — 예측 불가")
        else:
            models_loaded = []
            if xgb_model: models_loaded.append("XGBoost")
            if lgb_model: models_loaded.append("LightGBM")
            if cat_model: models_loaded.append("CatBoost")
            if meta_model: models_loaded.append("Stacking")
            logger.info(f"[{lg_key}] 앙상블 로드: {'+'.join(models_loaded)} v{version}")

        self._ensemble[lg_key] = (xgb_model, lgb_model, cat_model, meta_model, version or "no-model")

        # 스코어 모델 로드
        home_score, away_score, score_ver = load_score_models(league)
        if home_score is not None:
            logger.info(f"[{lg_key}] 스코어 회귀 모델 로드: v{score_ver}")
        self._score_models[lg_key] = (home_score, away_score, score_ver)

    def _get_models(self, league: str) -> tuple:
        key = league if league in self._ensemble else "default"
        if key not in self._ensemble:
            self._load_models(league)
            key = league
        return self._ensemble.get(key, (None, None, None, None, "no-model"))

    @property
    def model_version(self) -> str:
        key = self._league or "default"
        return self._ensemble.get(key, (None, None, None, None, "no-model"))[4]

    async def predict(self, game_id: int, db: AsyncSession) -> Optional[dict]:
        """경기에 대한 앙상블 예측 실행"""
        from sqlalchemy import select
        from app.models import Game

        game_result = await db.execute(select(Game).where(Game.id == game_id))
        game = game_result.scalar_one_or_none()
        if not game:
            return None

        if game.league not in self._ensemble:
            self._load_models(game.league)

        xgb_model, lgb_model, cat_model, meta_model, model_version = self._get_models(game.league)

        if xgb_model is None and lgb_model is None and cat_model is None:
            logger.error(f"[{game.league}] 모델 미로드 — 예측 불가")
            return None

        try:
            feature_array, snapshot = await build_features(db, game_id)
        except Exception as e:
            logger.warning(f"game_id={game_id} 피처 생성 실패: {e}")
            return None

        feature_2d = feature_array.reshape(1, -1)

        clean_snapshot = {
            k: (None if isinstance(v, float) and np.isnan(v) else v)
            for k, v in snapshot.items()
        }

        # 스코어 예측
        predicted_home_score = None
        predicted_away_score = None
        score_diff = 0.0
        lg_key = game.league if game.league in self._score_models else "default"
        score_tuple = self._score_models.get(lg_key, (None, None, None))
        home_score_model, away_score_model, _ = score_tuple
        if home_score_model is not None and away_score_model is not None:
            try:
                predicted_home_score = round(float(home_score_model.predict(feature_2d)[0]))
                predicted_away_score = round(float(away_score_model.predict(feature_2d)[0]))
                predicted_home_score = max(0, predicted_home_score)
                predicted_away_score = max(0, predicted_away_score)
                score_diff = float(predicted_home_score - predicted_away_score)
            except Exception as e:
                logger.warning(f"스코어 예측 실패 (game_id={game_id}): {e}")

        # 스코어 차이를 피처로 추가해 분류 모델 재입력
        feature_2d_aug = np.append(feature_2d, [[score_diff]], axis=1)

        try:
            xgb_prob = _get_prob(xgb_model, feature_2d_aug)
            lgb_prob = _get_prob(lgb_model, feature_2d_aug)
            cat_prob = _get_prob(cat_model, feature_2d_aug)

            base_probs = [p for p in [xgb_prob, lgb_prob, cat_prob] if p is not None]

            if not base_probs:
                logger.error(f"예측 실패: 모든 기본 모델에서 확률 없음 (game_id={game_id})")
                return None

            if meta_model is not None and len(base_probs) == 3:
                meta_input = np.array([[xgb_prob, lgb_prob, cat_prob]], dtype=np.float32)
                home_win_prob = float(meta_model.predict_proba(meta_input)[0][1])
            else:
                home_win_prob = float(np.mean(base_probs))

        except Exception as e:
            logger.error(f"스코어 반영 예측 오류 (game_id={game_id}): {e}")
            return None

        home_win_prob = max(0.01, min(0.99, home_win_prob))
        confidence = assign_confidence_tier(home_win_prob)
        predicted_winner_id = (
            game.home_team_id if home_win_prob >= 0.5 else game.away_team_id
        )

        return {
            "game_id": game_id,
            "model_version": model_version,
            "predicted_winner_id": predicted_winner_id,
            "home_win_prob": round(home_win_prob, 4),
            "confidence_tier": confidence,
            "feature_snapshot": clean_snapshot,
            "predicted_home_score": predicted_home_score,
            "predicted_away_score": predicted_away_score,
        }


def _get_prob(model, feature_2d) -> Optional[float]:
    """모델에서 홈팀 승리 확률 추출 (None=모델 없음)"""
    if model is None:
        return None
    try:
        if hasattr(model, "predict_proba"):
            return float(model.predict_proba(feature_2d)[0][1])
        else:
            return float(model.predict(feature_2d)[0])
    except Exception as e:
        logger.warning(f"모델 예측 실패: {e}")
        return None
