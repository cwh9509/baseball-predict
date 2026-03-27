"""
ML 모델 저장/로드 관리
모델 파일: {MODEL_PATH}/xgb-{league}-v{version}.ubj  (XGBoost)
            {MODEL_PATH}/lgb-{league}-v{version}.txt  (LightGBM)
            {MODEL_PATH}/cat-{league}-v{version}.cbm  (CatBoost)
            {MODEL_PATH}/meta-{league}-v{version}.pkl (Stacking meta)
"""
import json
import logging
import pickle
from pathlib import Path
from typing import Optional

from app.config import settings
from app.features.builder import FEATURE_COLUMNS

logger = logging.getLogger(__name__)

def get_model_dir() -> Path:
    return Path(settings.model_path)


def _metadata_file(league: str) -> str:
    return f"model_metadata_{league.lower()}.json"


def save_xgb_model(model, version: str, league: Optional[str] = None) -> Path:
    """XGBoost 모델 저장 (리그별)"""
    lg = (league or settings.league).upper()
    path = get_model_dir() / f"xgb-{lg.lower()}-v{version}.ubj"
    model.get_booster().save_model(str(path))
    _save_metadata(version, "xgboost", path, lg)
    logger.info(f"XGBoost 모델 저장: {path}")
    return path


def save_lgb_model(model, version: str, league: Optional[str] = None) -> Path:
    """LightGBM 모델 저장 (리그별, XGB와 별도 메타데이터)"""
    lg = (league or settings.league).upper()
    path = get_model_dir() / f"lgb-{lg.lower()}-v{version}.txt"
    model.booster_.save_model(str(path))
    metadata = {
        "version": version,
        "model_type": "lightgbm",
        "league": lg,
        "path": str(path),
        "feature_columns": FEATURE_COLUMNS,
        "n_features": len(FEATURE_COLUMNS),
    }
    meta_path = get_model_dir() / f"model_metadata_lgb_{lg.lower()}.json"
    meta_path.write_text(json.dumps(metadata, indent=2))
    logger.info(f"LightGBM 모델 저장: {path}")
    return path


def save_cat_model(model, version: str, league: Optional[str] = None) -> Path:
    """CatBoost 모델 저장 (리그별)"""
    lg = (league or settings.league).upper()
    path = get_model_dir() / f"cat-{lg.lower()}-v{version}.cbm"
    model.save_model(str(path))
    metadata = {
        "version": version,
        "model_type": "catboost",
        "league": lg,
        "path": str(path),
        "feature_columns": FEATURE_COLUMNS,
        "n_features": len(FEATURE_COLUMNS),
    }
    meta_path = get_model_dir() / f"model_metadata_cat_{lg.lower()}.json"
    meta_path.write_text(json.dumps(metadata, indent=2))
    logger.info(f"CatBoost 모델 저장: {path}")
    return path


def save_meta_model(model, version: str, league: Optional[str] = None) -> Path:
    """Stacking 메타 모델 저장 (sklearn LogisticRegression)"""
    lg = (league or settings.league).upper()
    path = get_model_dir() / f"meta-{lg.lower()}-v{version}.pkl"
    with open(path, "wb") as f:
        pickle.dump(model, f)
    metadata = {
        "version": version,
        "model_type": "stacking_meta",
        "league": lg,
        "path": str(path),
    }
    meta_path = get_model_dir() / f"model_metadata_meta_{lg.lower()}.json"
    meta_path.write_text(json.dumps(metadata, indent=2))
    logger.info(f"Stacking 메타 모델 저장: {path}")
    return path


def load_latest_model(league: Optional[str] = None):
    """최신 모델 자동 로드 (리그별, XGBoost 우선)"""
    lg = (league or settings.league).upper()
    metadata = _load_metadata(lg)
    if not metadata:
        metadata = _load_metadata_legacy()
    if not metadata:
        return None, None

    model_type = metadata.get("model_type")
    path = Path(metadata.get("path", ""))

    if not path.exists():
        filename = metadata.get("path", "").replace("\\", "/").split("/")[-1]
        path = get_model_dir() / filename
    if not path.exists():
        logger.error(f"모델 파일 없음: {path}")
        return None, None

    try:
        if model_type == "xgboost":
            import xgboost as xgb
            model = xgb.XGBClassifier()
            model.load_model(str(path))
            return model, metadata.get("version")
        elif model_type == "lightgbm":
            import lightgbm as lgb
            model = lgb.Booster(model_file=str(path))
            return model, metadata.get("version")
    except Exception as e:
        logger.error(f"모델 로드 실패: {e}")
        return None, None

    return None, None


def _save_metadata(version: str, model_type: str, path: Path, league: str) -> None:
    metadata = {
        "version": version,
        "model_type": model_type,
        "league": league,
        "path": str(path),
        "feature_columns": FEATURE_COLUMNS,
        "n_features": len(FEATURE_COLUMNS),
    }
    meta_path = get_model_dir() / _metadata_file(league)
    meta_path.write_text(json.dumps(metadata, indent=2))


def _load_metadata(league: str) -> Optional[dict]:
    meta_path = get_model_dir() / _metadata_file(league)
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text())
    except Exception:
        return None


def load_ensemble_models(league: Optional[str] = None) -> tuple:
    """XGBoost + LightGBM + CatBoost + Stacking 메타 모델 로드
    Returns: (xgb_model, lgb_model, cat_model, meta_model, version) — 없으면 None
    """
    lg = (league or settings.league).upper()
    xgb_meta_path = get_model_dir() / f"model_metadata_{lg.lower()}.json"
    lgb_meta_path = get_model_dir() / f"model_metadata_lgb_{lg.lower()}.json"
    cat_meta_path = get_model_dir() / f"model_metadata_cat_{lg.lower()}.json"
    meta_meta_path = get_model_dir() / f"model_metadata_meta_{lg.lower()}.json"

    xgb_model, xgb_version = None, None
    lgb_model, lgb_version = None, None
    cat_model, cat_version = None, None
    meta_model, meta_version = None, None

    def _resolve_path(stored: str) -> Path:
        p = Path(stored)
        if p.exists():
            return p
        filename = stored.replace("\\", "/").split("/")[-1]
        return get_model_dir() / filename

    if xgb_meta_path.exists():
        try:
            meta = json.loads(xgb_meta_path.read_text())
            path = _resolve_path(meta.get("path", ""))
            if path.exists():
                import xgboost as xgb
                xgb_model = xgb.XGBClassifier()
                xgb_model.load_model(str(path))
                xgb_version = meta.get("version")
            else:
                logger.error(f"XGBoost 모델 파일 없음: {path}")
        except Exception as e:
            logger.error(f"XGBoost 로드 실패: {e}")

    if lgb_meta_path.exists():
        try:
            meta = json.loads(lgb_meta_path.read_text())
            path = _resolve_path(meta.get("path", ""))
            if path.exists():
                import lightgbm as lgb_lib
                lgb_model = lgb_lib.Booster(model_file=str(path))
                lgb_version = meta.get("version")
            else:
                logger.error(f"LightGBM 모델 파일 없음: {path}")
        except Exception as e:
            logger.error(f"LightGBM 로드 실패: {e}")

    if cat_meta_path.exists():
        try:
            meta = json.loads(cat_meta_path.read_text())
            path = _resolve_path(meta.get("path", ""))
            if path.exists():
                from catboost import CatBoostClassifier
                cat_model = CatBoostClassifier()
                cat_model.load_model(str(path))
                cat_version = meta.get("version")
            else:
                logger.error(f"CatBoost 모델 파일 없음: {path}")
        except Exception as e:
            logger.error(f"CatBoost 로드 실패: {e}")

    if meta_meta_path.exists():
        try:
            meta = json.loads(meta_meta_path.read_text())
            path = _resolve_path(meta.get("path", ""))
            if path.exists():
                with open(path, "rb") as f:
                    meta_model = pickle.load(f)
                meta_version = meta.get("version")
            else:
                logger.error(f"Stacking 메타 모델 파일 없음: {path}")
        except Exception as e:
            logger.error(f"Stacking 메타 모델 로드 실패: {e}")

    version = xgb_version or lgb_version or cat_version or meta_version
    return xgb_model, lgb_model, cat_model, meta_model, version


def _load_metadata_legacy() -> Optional[dict]:
    """레거시 model_metadata.json (리그 구분 없던 구버전)"""
    meta_path = get_model_dir() / "model_metadata.json"
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text())
    except Exception:
        return None
