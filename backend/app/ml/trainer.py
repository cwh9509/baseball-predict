"""
ML 모델 학습기
- Optuna로 XGBoost + LightGBM + CatBoost 하이퍼파라미터 자동 튜닝
- 세 모델 OOF 예측값으로 LogisticRegression Stacking
- 반드시 TimeSeriesSplit 사용 — 랜덤 분할 시 데이터 누수 발생!

사용법:
  python -m app.ml.trainer
"""
import asyncio
import logging
from datetime import datetime

import numpy as np
from sklearn.base import clone
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit, cross_val_score

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.features.builder import get_feature_columns, build_features
from app.features.elo_features import invalidate_elo_cache
from app.ml.model_registry import save_xgb_model, save_lgb_model, save_cat_model, save_meta_model, save_score_models

logger = logging.getLogger(__name__)

N_OPTUNA_TRIALS = 100   # 튜닝 시도 횟수 (늘릴수록 정확하지만 느림)
N_CV_SPLITS = 5


class Trainer:

    async def retrain(self) -> str:
        """전체 재학습 파이프라인 실행"""
        logger.info("모델 재학습 시작 (Optuna + XGBoost + LightGBM + CatBoost + Stacking)")

        invalidate_elo_cache(settings.league)

        X, y = await self._collect_training_data()
        if len(X) < 100:
            logger.warning(f"학습 데이터 부족: {len(X)}개 (최소 100개 필요)")
            return "insufficient_data"

        logger.info(f"학습 데이터: {len(X)}개 경기")

        tscv = TimeSeriesSplit(n_splits=N_CV_SPLITS)
        version = datetime.now().strftime("%Y%m%d")

        # ── 1. XGBoost Optuna 튜닝 ─────────────────────────────────────
        xgb_model = await asyncio.to_thread(
            self._tune_and_fit_xgb, X, y, tscv, version
        )

        # ── 2. LightGBM Optuna 튜닝 ────────────────────────────────────
        lgb_model = await asyncio.to_thread(
            self._tune_and_fit_lgb, X, y, tscv, version
        )

        # ── 3. CatBoost Optuna 튜닝 ────────────────────────────────────
        cat_model = await asyncio.to_thread(
            self._tune_and_fit_catboost, X, y, tscv, version
        )

        # ── 4. Stacking 메타 모델 ──────────────────────────────────────
        meta_model = await asyncio.to_thread(
            self._build_stacking_model, xgb_model, lgb_model, cat_model, X, y, tscv
        )
        save_meta_model(meta_model, version, league=settings.league)
        logger.info("Stacking 메타 모델 저장 완료")

        # ── 5. 스코어 회귀 모델 ───────────────────────────────────────
        X_score, y_home, y_away = await self._collect_score_training_data()
        if len(X_score) >= 50:
            logger.info(f"스코어 회귀 학습 데이터: {len(X_score)}경기")
            home_score_model, away_score_model = await asyncio.to_thread(
                self._train_score_models, X_score, y_home, y_away, version
            )
        else:
            logger.warning(f"스코어 학습 데이터 부족: {len(X_score)}개 — 스코어 모델 건너뜀")

        # ── 6. 앙상블 CV 정확도 ────────────────────────────────────────
        self._log_ensemble_cv(xgb_model, lgb_model, cat_model, meta_model, X, y, tscv)

        # ── 7. 피처 중요도 ─────────────────────────────────────────────
        feature_cols = get_feature_columns(settings.league)
        importances = xgb_model.feature_importances_
        top5 = np.argsort(importances)[::-1][:5]
        logger.info("XGBoost 상위 피처:")
        for i in top5:
            logger.info(f"  {feature_cols[i]}: {importances[i]:.4f}")

        logger.info(f"모델 저장 완료: v{version}")
        return version

    # ──────────────────────────────────────────────────────────────────
    def _tune_and_fit_xgb(self, X, y, tscv, version: str):
        import optuna
        import xgboost as xgb

        optuna.logging.set_verbosity(optuna.logging.WARNING)

        def objective(trial):
            params = {
                "n_estimators":      trial.suggest_int("n_estimators", 200, 800),
                "max_depth":         trial.suggest_int("max_depth", 3, 8),
                "learning_rate":     trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
                "subsample":         trial.suggest_float("subsample", 0.6, 1.0),
                "colsample_bytree":  trial.suggest_float("colsample_bytree", 0.5, 1.0),
                "min_child_weight":  trial.suggest_int("min_child_weight", 1, 10),
                "gamma":             trial.suggest_float("gamma", 0.0, 0.5),
                "reg_alpha":         trial.suggest_float("reg_alpha", 0.0, 1.0),
                "reg_lambda":        trial.suggest_float("reg_lambda", 0.5, 2.0),
            }
            model = xgb.XGBClassifier(
                **params, eval_metric="logloss", random_state=42, n_jobs=-1
            )
            scores = cross_val_score(model, X, y, cv=tscv, scoring="accuracy")
            return scores.mean()

        logger.info(f"XGBoost Optuna 튜닝 시작 ({N_OPTUNA_TRIALS} trials)...")
        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=N_OPTUNA_TRIALS, show_progress_bar=False)

        best = study.best_params
        logger.info(f"XGBoost 최적 파라미터: {best}")
        logger.info(f"XGBoost 최적 CV 정확도: {study.best_value:.3f}")

        final_model = xgb.XGBClassifier(
            **best, eval_metric="logloss", random_state=42, n_jobs=-1
        )
        final_model.fit(X, y)
        save_xgb_model(final_model, version, league=settings.league)
        return final_model

    def _tune_and_fit_lgb(self, X, y, tscv, version: str):
        import optuna
        import lightgbm as lgb

        optuna.logging.set_verbosity(optuna.logging.WARNING)

        def objective(trial):
            params = {
                "n_estimators":       trial.suggest_int("n_estimators", 200, 800),
                "max_depth":          trial.suggest_int("max_depth", 3, 8),
                "learning_rate":      trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
                "num_leaves":         trial.suggest_int("num_leaves", 20, 127),
                "subsample":          trial.suggest_float("subsample", 0.6, 1.0),
                "colsample_bytree":   trial.suggest_float("colsample_bytree", 0.5, 1.0),
                "min_child_samples":  trial.suggest_int("min_child_samples", 10, 50),
                "reg_alpha":          trial.suggest_float("reg_alpha", 0.0, 1.0),
                "reg_lambda":         trial.suggest_float("reg_lambda", 0.0, 2.0),
            }
            model = lgb.LGBMClassifier(**params, random_state=42, verbose=-1, n_jobs=-1)
            scores = cross_val_score(model, X, y, cv=tscv, scoring="accuracy")
            return scores.mean()

        logger.info(f"LightGBM Optuna 튜닝 시작 ({N_OPTUNA_TRIALS} trials)...")
        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=N_OPTUNA_TRIALS, show_progress_bar=False)

        best = study.best_params
        logger.info(f"LightGBM 최적 파라미터: {best}")
        logger.info(f"LightGBM 최적 CV 정확도: {study.best_value:.3f}")

        final_model = lgb.LGBMClassifier(**best, random_state=42, verbose=-1, n_jobs=-1)
        final_model.fit(X, y)
        save_lgb_model(final_model, version, league=settings.league)
        return final_model

    def _tune_and_fit_catboost(self, X, y, tscv, version: str):
        import optuna
        from catboost import CatBoostClassifier

        optuna.logging.set_verbosity(optuna.logging.WARNING)

        def objective(trial):
            params = {
                "iterations":           trial.suggest_int("iterations", 200, 800),
                "depth":                trial.suggest_int("depth", 4, 10),
                "learning_rate":        trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
                "l2_leaf_reg":          trial.suggest_float("l2_leaf_reg", 1.0, 10.0, log=True),
                "bagging_temperature":  trial.suggest_float("bagging_temperature", 0.0, 1.0),
                "border_count":         trial.suggest_int("border_count", 32, 255),
            }
            scores = []
            for train_idx, val_idx in tscv.split(X):
                m = CatBoostClassifier(**params, random_seed=42, verbose=0, allow_writing_files=False)
                m.fit(X[train_idx], y[train_idx])
                preds = m.predict(X[val_idx])
                scores.append((preds == y[val_idx]).mean())
            return float(np.mean(scores))

        logger.info(f"CatBoost Optuna 튜닝 시작 ({N_OPTUNA_TRIALS} trials)...")
        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=N_OPTUNA_TRIALS, show_progress_bar=False)

        best = study.best_params
        logger.info(f"CatBoost 최적 파라미터: {best}")
        logger.info(f"CatBoost 최적 CV 정확도: {study.best_value:.3f}")

        final_model = CatBoostClassifier(**best, random_seed=42, verbose=0, allow_writing_files=False)
        final_model.fit(X, y)
        save_cat_model(final_model, version, league=settings.league)
        return final_model

    def _build_stacking_model(self, xgb_model, lgb_model, cat_model, X, y, tscv):
        """OOF 예측으로 Stacking 메타 모델 학습"""
        n = len(X)
        meta_X = np.zeros((n, 3), dtype=np.float32)

        for train_idx, val_idx in tscv.split(X):
            X_tr, X_val = X[train_idx], X[val_idx]
            y_tr = y[train_idx]

            # clone으로 원본 모델 수정 없이 CV용 학습
            xgb_tmp = clone(xgb_model)
            lgb_tmp = clone(lgb_model)

            xgb_tmp.fit(X_tr, y_tr)
            lgb_tmp.fit(X_tr, y_tr)

            # CatBoost는 clone() 대신 파라미터 복사
            from catboost import CatBoostClassifier
            _cat_params = {**cat_model.get_params(), "verbose": 0, "allow_writing_files": False}
            cat_tmp = CatBoostClassifier(**_cat_params)
            cat_tmp.fit(X_tr, y_tr)

            meta_X[val_idx, 0] = xgb_tmp.predict_proba(X_val)[:, 1]
            meta_X[val_idx, 1] = lgb_tmp.predict_proba(X_val)[:, 1]
            meta_X[val_idx, 2] = cat_tmp.predict_proba(X_val)[:, 1]

        meta_model = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
        meta_model.fit(meta_X, y)

        # 메타 모델 가중치 로깅
        coefs = meta_model.coef_[0]
        logger.info(f"Stacking 가중치 — XGB: {coefs[0]:.3f}, LGB: {coefs[1]:.3f}, CAT: {coefs[2]:.3f}")

        return meta_model

    def _log_ensemble_cv(self, xgb_model, lgb_model, cat_model, meta_model, X, y, tscv):
        """Stacking CV 정확도 계산"""
        scores = []
        for train_idx, val_idx in tscv.split(X):
            X_tr, X_val = X[train_idx], X[val_idx]
            y_tr, y_val = y[train_idx], y[val_idx]

            xgb_tmp = clone(xgb_model); xgb_tmp.fit(X_tr, y_tr)
            lgb_tmp = clone(lgb_model); lgb_tmp.fit(X_tr, y_tr)

            from catboost import CatBoostClassifier
            _cat_params = {**cat_model.get_params(), "verbose": 0, "allow_writing_files": False}
            cat_tmp = CatBoostClassifier(**_cat_params)
            cat_tmp.fit(X_tr, y_tr)

            meta_X_val = np.column_stack([
                xgb_tmp.predict_proba(X_val)[:, 1],
                lgb_tmp.predict_proba(X_val)[:, 1],
                cat_tmp.predict_proba(X_val)[:, 1],
            ])
            preds = meta_model.predict(meta_X_val)
            scores.append((preds == y_val).mean())

        logger.info(f"Stacking 앙상블 CV 정확도: {np.mean(scores):.3f} ± {np.std(scores):.3f}")

    def _train_score_models(self, X, y_home, y_away, version: str):
        """홈/원정 득점 회귀 모델 학습"""
        import xgboost as xgb

        home_model = xgb.XGBRegressor(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
        )
        away_model = xgb.XGBRegressor(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
        )
        home_model.fit(X, y_home)
        away_model.fit(X, y_away)
        save_score_models(home_model, away_model, version, league=settings.league)
        logger.info("스코어 회귀 모델 저장 완료")
        return home_model, away_model

    async def _collect_score_training_data(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """스코어 회귀용 학습 데이터 수집 (home_score, away_score 있는 경기만)"""
        from sqlalchemy import select
        from app.models import Game

        X_rows, y_home, y_away = [], [], []

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Game).where(
                    Game.status == "final",
                    Game.winner_team_id.isnot(None),
                    Game.home_score.isnot(None),
                    Game.away_score.isnot(None),
                    Game.league == settings.league,
                ).order_by(Game.game_date.asc())
            )
            games = result.scalars().all()

            for game in games:
                try:
                    feature_array, _ = await build_features(db, game.id)
                    X_rows.append(feature_array)
                    y_home.append(float(game.home_score))
                    y_away.append(float(game.away_score))
                except Exception:
                    pass

        if not X_rows:
            return np.array([]), np.array([]), np.array([])

        return np.array(X_rows), np.array(y_home), np.array(y_away)

    async def _collect_training_data(self) -> tuple[np.ndarray, np.ndarray]:
        from sqlalchemy import select
        from app.models import Game

        X_rows, y_labels = [], []

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Game).where(
                    Game.status == "final",
                    Game.winner_team_id.isnot(None),
                    Game.league == settings.league,
                ).order_by(Game.game_date.asc())
            )
            games = result.scalars().all()

            logger.info(f"완료 경기 {len(games)}개 피처 생성 중...")
            for game in games:
                try:
                    feature_array, _ = await build_features(db, game.id)
                    label = 1 if game.winner_team_id == game.home_team_id else 0
                    X_rows.append(feature_array)
                    y_labels.append(label)
                except Exception as e:
                    logger.debug(f"game_id={game.id} 피처 생성 건너뜀: {e}")

        if not X_rows:
            return np.array([]), np.array([])

        return np.array(X_rows), np.array(y_labels)


class Evaluator:
    async def evaluate_recent(self, days: int = 7) -> dict:
        from sqlalchemy import select, func
        from app.models import Prediction

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(
                    func.count(Prediction.id).label("total"),
                    func.sum(func.cast(Prediction.was_correct, int)).label("correct"),
                ).where(Prediction.was_correct.isnot(None))
            )
            row = result.one()
            total = row.total or 0
            correct = row.correct or 0
            accuracy = correct / total if total > 0 else 0.0

        if total > 10 and accuracy < 0.52:
            logger.warning(
                f"모델 정확도 경고: {accuracy:.1%} (롤링 < 52%) — 재학습 고려"
            )

        return {
            "total_predictions": total,
            "correct": correct,
            "accuracy": round(accuracy, 4),
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    asyncio.run(Trainer().retrain())
