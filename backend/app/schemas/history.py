from datetime import date
from typing import Optional
from pydantic import BaseModel


class AccuracyByTier(BaseModel):
    total: int
    accuracy: float


class HistorySummary(BaseModel):
    total_predictions: int
    correct: int
    accuracy: float
    by_confidence: dict[str, AccuracyByTier]


class PredictionHistoryItem(BaseModel):
    game_id: int
    game_date: date
    matchup: str
    predicted_winner: str
    actual_winner: Optional[str] = None
    home_win_prob: float
    was_correct: Optional[bool] = None
    confidence_tier: str


class HistoryResponse(BaseModel):
    summary: HistorySummary
    predictions: list[PredictionHistoryItem]
    pagination: dict
