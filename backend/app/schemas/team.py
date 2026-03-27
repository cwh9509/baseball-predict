from typing import Optional
from pydantic import BaseModel


class RecordSchema(BaseModel):
    wins: int
    losses: int
    win_pct: float


class TeamStatsResponse(BaseModel):
    team: dict
    season: int
    season_record: RecordSchema
    last_n_games: dict
    pitching: dict
    batting: dict
    home_record: RecordSchema
    away_record: RecordSchema
