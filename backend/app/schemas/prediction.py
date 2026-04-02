from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class KeyFactor(BaseModel):
    factor: str
    detail: str
    impact: str   # "positive" | "negative" | "neutral"


class ExplanationSchema(BaseModel):
    summary: str
    key_factors: list[KeyFactor]
    confidence_note: str


class LineupEntrySchema(BaseModel):
    order: int
    name: str
    position: str = ""


class LineupSchema(BaseModel):
    home_starter: Optional[str] = None
    away_starter: Optional[str] = None
    home_lineup: list[LineupEntrySchema] = []
    away_lineup: list[LineupEntrySchema] = []
    lineup_locked: bool = False


class PredictionDetailResponse(BaseModel):
    game_id: int
    game_date: Optional[str] = None
    home_team: Optional[dict] = None   # {id, name, short_name}
    away_team: Optional[dict] = None
    model_version: str
    predicted_at: datetime
    home_win_prob: float
    away_win_prob: float
    predicted_winner: dict   # {id, name}
    confidence_tier: str
    feature_snapshot: dict
    predicted_home_score: Optional[int] = None
    predicted_away_score: Optional[int] = None
    explanation: Optional[ExplanationSchema] = None
    lineup: Optional[LineupSchema] = None
    home_recent_results: list[bool] = []
    away_recent_results: list[bool] = []
