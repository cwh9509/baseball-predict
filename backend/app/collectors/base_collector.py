"""
수집기 추상 기본 클래스
KBO와 MLB 수집기가 동일한 인터페이스를 구현하도록 강제
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class GameRaw:
    """정규화 전 경기 원시 데이터"""
    external_game_id: str
    league: str
    game_date: date
    home_team_short: str
    away_team_short: str
    venue: str
    status: str
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    home_starter_external_id: Optional[str] = None
    away_starter_external_id: Optional[str] = None
    home_starter_name: Optional[str] = None   # KBO/NPB 선발투수 이름
    away_starter_name: Optional[str] = None
    game_time_local: Optional[str] = None    # "HH:MM" 형식


@dataclass
class GameLogRaw:
    """팀 최근 경기 로그"""
    game_date: date
    team_short: str
    opponent_short: str
    is_home: bool
    runs_scored: int
    runs_allowed: int
    win: bool
    starter_external_id: Optional[str] = None


@dataclass
class PitcherStatsRaw:
    """투수 시즌 통계"""
    external_id: str
    name: str
    team_short: str
    season: int
    era: float
    whip: float
    k9: float            # 9이닝당 삼진
    ip: float            # 이닝
    wins: int
    losses: int
    last_appearance_date: Optional[date] = None
    handedness: Optional[str] = None   # "L" or "R"


@dataclass
class TeamRaw:
    """팀 기본 정보"""
    league: str
    short_name: str
    name: str
    city: str
    stadium_name: str
    stadium_lat: Optional[float] = None
    stadium_lon: Optional[float] = None
    roof_type: str = "open"   # open / retractable / dome


class BaseCollector(ABC):
    """모든 리그 수집기의 공통 인터페이스"""

    @abstractmethod
    async def fetch_schedule(self, target_date: date) -> list[GameRaw]:
        """특정 날짜의 경기 일정 수집"""
        ...

    @abstractmethod
    async def fetch_game_results(self, target_date: date) -> list[GameRaw]:
        """특정 날짜의 경기 결과 수집 (점수 포함)"""
        ...

    @abstractmethod
    async def fetch_team_game_log(self, team_short: str, n_games: int = 10) -> list[GameLogRaw]:
        """팀의 최근 N경기 로그 수집"""
        ...

    @abstractmethod
    async def fetch_pitcher_stats(self, external_id: str, season: int) -> Optional[PitcherStatsRaw]:
        """선발투수 시즌 통계 수집"""
        ...

    @abstractmethod
    async def fetch_all_teams(self) -> list[TeamRaw]:
        """전체 팀 목록 수집"""
        ...
