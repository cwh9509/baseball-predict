"""모델 입출력용 피처 행렬 — sklearn/LightGBM feature name 경고 방지"""
import numpy as np
import pandas as pd

from app.features.builder import get_feature_columns


def classifier_feature_columns(league: str) -> list[str]:
    return get_feature_columns(league) + ["predicted_score_diff"]


def score_feature_columns(league: str) -> list[str]:
    return get_feature_columns(league)


def to_classifier_frame(X: np.ndarray, league: str) -> pd.DataFrame:
    cols = classifier_feature_columns(league)
    arr = np.asarray(X, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    return pd.DataFrame(arr, columns=cols[: arr.shape[1]])


def to_score_frame(X: np.ndarray, league: str) -> pd.DataFrame:
    cols = score_feature_columns(league)
    arr = np.asarray(X, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    return pd.DataFrame(arr, columns=cols[: arr.shape[1]])
