from datetime import date, time
from typing import Optional
from pydantic import BaseModel


class TeamBrief(BaseModel):
    id: int
    name: str
    short_name: str
    league: str

    class Config:
        from_attributes = True


class StarterBrief(BaseModel):
    id: int
    name: str
    era: Optional[float] = None

    class Config:
        from_attributes = True


class WeatherBrief(BaseModel):
    temperature_c: Optional[float] = None
    weather_main: Optional[str] = None
    wind_speed_ms: Optional[float] = None
    is_raining: Optional[bool] = None


class PredictionBrief(BaseModel):
    home_win_prob: float
    predicted_winner: str
    confidence_tier: str
    has_explanation: bool
    predicted_home_score: Optional[int] = None
    predicted_away_score: Optional[int] = None


class GameResponse(BaseModel):
    id: int
    game_date: date
    game_time: Optional[str] = None
    status: str
    home_team: TeamBrief
    away_team: TeamBrief
    home_starter: Optional[StarterBrief] = None
    away_starter: Optional[StarterBrief] = None
    venue: Optional[str] = None
    lineup_locked: bool = False
    prediction: Optional[PredictionBrief] = None
    weather: Optional[WeatherBrief] = None


class GamesListResponse(BaseModel):
    date: str
    league: str
    games: list[GameResponse]
