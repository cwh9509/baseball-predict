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
from app.ml.feature_matrix import classifier_feature_columns, score_feature_columns, to_classifier_frame, to_score_frame
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
        xgb_model, lgb_model, cat_model, meta_model, calibrator, version = load_ensemble_models(league)

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

        self._ensemble[lg_key] = (
            xgb_model, lgb_model, cat_model, meta_model, calibrator, version or "no-model"
        )

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
        return self._ensemble.get(key, (None, None, None, None, None, "no-model"))

    @property
    def model_version(self) -> str:
        key = self._league or "default"
        return self._ensemble.get(key, (None, None, None, None, None, "no-model"))[5]

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

        xgb_model, lgb_model, cat_model, meta_model, calibrator, model_version = self._get_models(game.league)

        if xgb_model is None and lgb_model is None and cat_model is None:
            logger.error(f"[{game.league}] 모델 미로드 — 예측 불가")
            return None

        try:
            feature_array, snapshot = await build_features(db, game_id)
        except Exception as e:
            logger.warning(f"game_id={game_id} 피처 생성 실패: {e}")
            return None

        lg_key = game.league if game.league in self._score_models else "default"
        home_score_model, away_score_model, _ = self._score_models.get(lg_key, (None, None, None))

        score_features = to_score_frame(feature_array, game.league)
        classifier_features = to_classifier_frame(
            np.append(feature_array, 0.0), game.league
        )

        mismatch = _feature_count_mismatch(
            game.league, xgb_model, lgb_model, cat_model, home_score_model, away_score_model,
            len(score_features.columns), len(classifier_features.columns),
        )
        if mismatch:
            logger.error(f"[{game.league}] {mismatch} — retrain?league={game.league} 후 collect 하세요 (game_id={game_id})")
            return None

        clean_snapshot = {
            k: (None if isinstance(v, float) and np.isnan(v) else v)
            for k, v in snapshot.items()
        }

        # 스코어 예측
        predicted_home_score = None
        predicted_away_score = None
        score_diff = 0.0
        if home_score_model is not None and away_score_model is not None:
            try:
                predicted_home_score = max(0, round(float(home_score_model.predict(score_features)[0])))
                predicted_away_score = max(0, round(float(away_score_model.predict(score_features)[0])))
                score_diff = float(predicted_home_score - predicted_away_score)
            except Exception as e:
                logger.warning(f"스코어 예측 실패 (game_id={game_id}): {e}")

        classifier_features = to_classifier_frame(
            np.append(feature_array, score_diff), game.league
        )

        try:
            xgb_prob = _get_prob(xgb_model, classifier_features)
            lgb_prob = _get_prob(lgb_model, classifier_features)
            cat_prob = _get_prob(cat_model, classifier_features)

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

        if calibrator is not None:
            try:
                home_win_prob = float(calibrator.predict([home_win_prob])[0])
            except Exception as e:
                logger.debug(f"캘리브레이션 적용 실패 (game_id={game_id}): {e}")

        home_win_prob = max(0.01, min(0.99, home_win_prob))
        confidence = assign_confidence_tier(home_win_prob)
        predicted_winner_id = (
            game.home_team_id if home_win_prob >= 0.5 else game.away_team_id
        )

        # 승패 확률과 예상 스코어 일관성 보정
        # 분류 모델(홈팀 승)인데 스코어가 홈팀 패로 나오면 스코어를 맞춰줌
        if predicted_home_score is not None and predicted_away_score is not None:
            home_wins_by_prob = home_win_prob >= 0.5
            home_wins_by_score = predicted_home_score >= predicted_away_score
            if home_wins_by_prob != home_wins_by_score:
                # 점수를 교환하여 일관성 맞춤
                predicted_home_score, predicted_away_score = predicted_away_score, predicted_home_score

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


def _model_n_features(model) -> Optional[int]:
    if model is None:
        return None
    if hasattr(model, "n_features_in_") and model.n_features_in_ is not None:
        return int(model.n_features_in_)
    try:
        return int(model.num_feature())
    except Exception:
        pass
    try:
        return int(model.feature_count_)
    except Exception:
        return None


def _feature_count_mismatch(
    league: str,
    xgb_model,
    lgb_model,
    cat_model,
    home_score_model,
    away_score_model,
    score_n: int,
    classifier_n: int,
) -> Optional[str]:
    expected_score = len(score_feature_columns(league))
    expected_cls = len(classifier_feature_columns(league))
    if score_n != expected_score or classifier_n != expected_cls:
        return (
            f"피처 생성 오류: score={score_n}(기대 {expected_score}), "
            f"classifier={classifier_n}(기대 {expected_cls})"
        )

    for label, model, expected in (
        ("XGB", xgb_model, expected_cls),
        ("LGB", lgb_model, expected_cls),
        ("CAT", cat_model, expected_cls),
        ("score_home", home_score_model, expected_score),
        ("score_away", away_score_model, expected_score),
    ):
        model_n = _model_n_features(model)
        if model_n is not None and model_n != expected:
            return f"{label} 모델 피처 수 불일치: 모델={model_n}, 코드={expected}"
    return None


def _get_prob(model, features) -> Optional[float]:
    """모델에서 홈팀 승리 확률 추출 (None=모델 없음)"""
    if model is None:
        return None
    try:
        if hasattr(model, "predict_proba"):
            return float(model.predict_proba(features)[0][1])
        else:
            return float(model.predict(features)[0])
    except Exception as e:
        logger.warning(f"모델 예측 실패: {e}")
        return None
