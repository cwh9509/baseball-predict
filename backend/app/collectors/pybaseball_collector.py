"""
MLB 데이터 수집기 — pybaseball 라이브러리 사용
원시 응답은 data/raw/ 에 Parquet 형식으로 캐시하여 재요청 방지

주요 pybaseball 함수:
  schedule_and_record(season, team) → 팀 시즌 일정+결과
  pitching_stats(start, end, qual)  → 투수 시즌 통계
  playerid_lookup(last, first)      → 선수 ID 조회
"""
import asyncio
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from app.collectors.base_collector import (
    BaseCollector,
    GameLogRaw,
    GameRaw,
    PitcherStatsRaw,
    TeamRaw,
)

logger = logging.getLogger(__name__)

# Parquet 캐시 경로
CACHE_DIR = Path(os.environ.get("DATA_RAW_PATH", "data/raw"))

# MLB 30개 구단 정보 (구장 좌표 포함)
# 팀 전체 이름 → 약자 역매핑 (statsapi는 전체 이름 반환)
# 런타임에 MLB_TEAMS 정의 후 아래에서 생성
_MLB_NAME_TO_SHORT: dict[str, str] = {}

MLB_TEAMS: dict[str, dict] = {
    "ARI": {"name": "Arizona Diamondbacks", "city": "Phoenix", "stadium": "Chase Field",
             "lat": 33.4453, "lon": -112.0667, "roof": "retractable"},
    "ATL": {"name": "Atlanta Braves", "city": "Atlanta", "stadium": "Truist Park",
             "lat": 33.8908, "lon": -84.4678, "roof": "open"},
    "BAL": {"name": "Baltimore Orioles", "city": "Baltimore", "stadium": "Oriole Park at Camden Yards",
             "lat": 39.2838, "lon": -76.6218, "roof": "open"},
    "BOS": {"name": "Boston Red Sox", "city": "Boston", "stadium": "Fenway Park",
             "lat": 42.3467, "lon": -71.0972, "roof": "open"},
    "CHC": {"name": "Chicago Cubs", "city": "Chicago", "stadium": "Wrigley Field",
             "lat": 41.9484, "lon": -87.6553, "roof": "open"},
    "CWS": {"name": "Chicago White Sox", "city": "Chicago", "stadium": "Guaranteed Rate Field",
             "lat": 41.8299, "lon": -87.6338, "roof": "open"},
    "CIN": {"name": "Cincinnati Reds", "city": "Cincinnati", "stadium": "Great American Ball Park",
             "lat": 39.0975, "lon": -84.5080, "roof": "open"},
    "CLE": {"name": "Cleveland Guardians", "city": "Cleveland", "stadium": "Progressive Field",
             "lat": 41.4962, "lon": -81.6852, "roof": "open"},
    "COL": {"name": "Colorado Rockies", "city": "Denver", "stadium": "Coors Field",
             "lat": 39.7559, "lon": -104.9942, "roof": "open"},
    "DET": {"name": "Detroit Tigers", "city": "Detroit", "stadium": "Comerica Park",
             "lat": 42.3390, "lon": -83.0485, "roof": "open"},
    "HOU": {"name": "Houston Astros", "city": "Houston", "stadium": "Minute Maid Park",
             "lat": 29.7572, "lon": -95.3552, "roof": "retractable"},
    "KC":  {"name": "Kansas City Royals", "city": "Kansas City", "stadium": "Kauffman Stadium",
             "lat": 39.0517, "lon": -94.4803, "roof": "open"},
    "LAA": {"name": "Los Angeles Angels", "city": "Anaheim", "stadium": "Angel Stadium",
             "lat": 33.8003, "lon": -117.8827, "roof": "open"},
    "LAD": {"name": "Los Angeles Dodgers", "city": "Los Angeles", "stadium": "Dodger Stadium",
             "lat": 34.0739, "lon": -118.2400, "roof": "open"},
    "MIA": {"name": "Miami Marlins", "city": "Miami", "stadium": "loanDepot park",
             "lat": 25.7781, "lon": -80.2197, "roof": "retractable"},
    "MIL": {"name": "Milwaukee Brewers", "city": "Milwaukee", "stadium": "American Family Field",
             "lat": 43.0280, "lon": -87.9712, "roof": "retractable"},
    "MIN": {"name": "Minnesota Twins", "city": "Minneapolis", "stadium": "Target Field",
             "lat": 44.9817, "lon": -93.2781, "roof": "open"},
    "NYM": {"name": "New York Mets", "city": "New York", "stadium": "Citi Field",
             "lat": 40.7571, "lon": -73.8458, "roof": "open"},
    "NYY": {"name": "New York Yankees", "city": "New York", "stadium": "Yankee Stadium",
             "lat": 40.8296, "lon": -73.9262, "roof": "open"},
    "OAK": {"name": "Oakland Athletics", "city": "Oakland", "stadium": "Oakland Coliseum",
             "lat": 37.7516, "lon": -122.2005, "roof": "open"},
    "PHI": {"name": "Philadelphia Phillies", "city": "Philadelphia", "stadium": "Citizens Bank Park",
             "lat": 39.9061, "lon": -75.1665, "roof": "open"},
    "PIT": {"name": "Pittsburgh Pirates", "city": "Pittsburgh", "stadium": "PNC Park",
             "lat": 40.4469, "lon": -80.0057, "roof": "open"},
    "SD":  {"name": "San Diego Padres", "city": "San Diego", "stadium": "Petco Park",
             "lat": 32.7076, "lon": -117.1570, "roof": "open"},
    "SF":  {"name": "San Francisco Giants", "city": "San Francisco", "stadium": "Oracle Park",
             "lat": 37.7786, "lon": -122.3893, "roof": "open"},
    "SEA": {"name": "Seattle Mariners", "city": "Seattle", "stadium": "T-Mobile Park",
             "lat": 47.5914, "lon": -122.3325, "roof": "retractable"},
    "STL": {"name": "St. Louis Cardinals", "city": "St. Louis", "stadium": "Busch Stadium",
             "lat": 38.6226, "lon": -90.1928, "roof": "open"},
    "TB":  {"name": "Tampa Bay Rays", "city": "St. Petersburg", "stadium": "Tropicana Field",
             "lat": 27.7683, "lon": -82.6534, "roof": "dome"},
    "TEX": {"name": "Texas Rangers", "city": "Arlington", "stadium": "Globe Life Field",
             "lat": 32.7473, "lon": -97.0827, "roof": "retractable"},
    "TOR": {"name": "Toronto Blue Jays", "city": "Toronto", "stadium": "Rogers Centre",
             "lat": 43.6414, "lon": -79.3894, "roof": "retractable"},
    "WSH": {"name": "Washington Nationals", "city": "Washington D.C.", "stadium": "Nationals Park",
             "lat": 38.8730, "lon": -77.0074, "roof": "open"},
}


# MLB_TEAMS 정의 후 역매핑 생성
_MLB_NAME_TO_SHORT = {info["name"]: short for short, info in MLB_TEAMS.items()}
# 팀 이전/변경 등 예외 케이스 추가
_MLB_NAME_TO_SHORT.update({
    "Athletics": "OAK",          # 오클랜드→새크라멘토 이전 후 팀명 변경
    "Cleveland Indians": "CLE",  # 구 이름 호환
    "Miami Marlins": "MIA",
})


def _resolve_mlb_short(name: str) -> str:
    """팀 전체 이름 → 약자 변환. 부분 일치도 지원."""
    if not name:
        return "UNK"
    if name in _MLB_NAME_TO_SHORT:
        return _MLB_NAME_TO_SHORT[name]
    # 부분 일치 (예: "St. Louis" → "STL")
    name_lower = name.lower()
    for full, short in _MLB_NAME_TO_SHORT.items():
        if name_lower in full.lower() or full.lower() in name_lower:
            return short
    # 마지막 단어(팀 닉네임)로 매핑 시도
    last_word = name.split()[-1] if name.split() else ""
    for full, short in _MLB_NAME_TO_SHORT.items():
        if last_word and full.endswith(last_word):
            return short
    logger.warning(f"MLB 팀 이름 매핑 실패: '{name}'")
    return name[:3].upper()


class PybaseballCollector(BaseCollector):
    """
    pybaseball 기반 MLB 데이터 수집기
    모든 pybaseball 호출은 동기이므로 asyncio.to_thread로 실행
    """

    def __init__(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    async def fetch_all_teams(self) -> list[TeamRaw]:
        return [
            TeamRaw(
                league="MLB",
                short_name=short,
                name=info["name"],
                city=info["city"],
                stadium_name=info["stadium"],
                stadium_lat=info["lat"],
                stadium_lon=info["lon"],
                roof_type=info["roof"],
            )
            for short, info in MLB_TEAMS.items()
        ]

    async def fetch_schedule(self, target_date: date) -> list[GameRaw]:
        """특정 날짜의 경기 일정 수집 (statsapi 사용)"""
        return await asyncio.to_thread(self._fetch_schedule_sync, target_date)

    def _fetch_schedule_sync(self, target_date: date) -> list[GameRaw]:
        import statsapi  # pip install MLB-StatsAPI

        cache_key = f"schedule_mlb_{target_date.isoformat()}"
        cached = self._load_cache(cache_key)
        if cached is not None:
            return self._df_to_game_raws(cached, target_date)

        try:
            data = statsapi.schedule(
                date=target_date.strftime("%m/%d/%Y"),
                sportId=1,
            )
            df = pd.DataFrame(data)
            if df.empty:
                return []
            self._save_cache(df, cache_key)
            return self._df_to_game_raws(df, target_date)
        except Exception as e:
            logger.error(f"MLB 일정 수집 실패 ({target_date}): {e}")
            return []

    def _df_to_game_raws(self, df: pd.DataFrame, target_date: date) -> list[GameRaw]:
        # 정규시즌(R)·포스트시즌(P·F·D·L·W) 만 포함, 스프링캠프(S)·마이너(E) 제외
        _VALID_GAME_TYPES = {"R", "F", "D", "L", "W", "P"}
        games = []
        for _, row in df.iterrows():
            if row.get("game_type") and row.get("game_type") not in _VALID_GAME_TYPES:
                continue
            home_short = _resolve_mlb_short(row.get("home_name", ""))
            away_short = _resolve_mlb_short(row.get("away_name", ""))
            if not home_short or not away_short:
                continue
            games.append(
                GameRaw(
                    external_game_id=str(row.get("game_id", "")),
                    league="MLB",
                    game_date=target_date,
                    home_team_short=home_short,
                    away_team_short=away_short,
                    venue=row.get("venue_name", ""),
                    status=row.get("status", "scheduled").lower(),
                    home_score=row.get("home_score") if row.get("status") == "Final" else None,
                    away_score=row.get("away_score") if row.get("status") == "Final" else None,
                    home_starter_external_id=str(row.get("home_probable_pitcher_id", "")) or None,
                    away_starter_external_id=str(row.get("away_probable_pitcher_id", "")) or None,
                    game_time_local=row.get("game_datetime", "")[:16],
                )
            )
        return games

    async def fetch_game_results(self, target_date: date) -> list[GameRaw]:
        return await self.fetch_schedule(target_date)

    async def fetch_team_game_log(self, team_short: str, n_games: int = 10) -> list[GameLogRaw]:
        """팀 최근 N경기 로그 (pybaseball schedule_and_record 사용)"""
        return await asyncio.to_thread(self._fetch_team_log_sync, team_short, n_games)

    def _fetch_team_log_sync(self, team_short: str, n_games: int) -> list[GameLogRaw]:
        import pybaseball as pb

        season = date.today().year
        cache_key = f"team_log_{team_short}_{season}"
        cached = self._load_cache(cache_key)

        if cached is None:
            try:
                # pybaseball team id 매핑 (팀 약자 → id)
                team_id = self._get_team_id(team_short)
                if team_id is None:
                    return []
                df = pb.schedule_and_record(season, team_id)
                if df is None or df.empty:
                    return []
                self._save_cache(df, cache_key)
                cached = df
            except Exception as e:
                logger.error(f"팀 경기 로그 수집 실패 ({team_short}): {e}")
                return []

        # 완료된 경기만 필터링 후 최근 N개
        finished = cached[cached["W/L"].notna()].tail(n_games)
        logs = []
        for _, row in finished.iterrows():
            try:
                is_home = "@" not in str(row.get("Unnamed: 4", ""))
                opp = str(row.get("Opp", ""))
                r = int(row.get("R", 0))
                ra = int(row.get("RA", 0))
                wl = str(row.get("W/L", ""))
                logs.append(
                    GameLogRaw(
                        game_date=pd.to_datetime(row["Date"]).date(),
                        team_short=team_short,
                        opponent_short=opp,
                        is_home=is_home,
                        runs_scored=r,
                        runs_allowed=ra,
                        win=wl.startswith("W"),
                    )
                )
            except Exception:
                continue
        return logs

    async def fetch_pitcher_stats(self, external_id: str, season: int) -> Optional[PitcherStatsRaw]:
        return await asyncio.to_thread(self._fetch_pitcher_sync, external_id, season)

    def _fetch_pitcher_sync(self, external_id: str, season: int) -> Optional[PitcherStatsRaw]:
        import pybaseball as pb

        cache_key = f"pitcher_{external_id}_{season}"
        cached = self._load_cache(cache_key)

        if cached is None:
            try:
                df = pb.pitching_stats(season, season, qual=1)
                if df is None or df.empty:
                    return None
                self._save_cache(df, f"pitching_stats_{season}")
                cached = df
            except Exception as e:
                logger.error(f"투수 통계 수집 실패 ({external_id}): {e}")
                return None

        # external_id로 해당 투수 찾기
        row = cached[cached["IDfg"].astype(str) == str(external_id)]
        if row.empty:
            return None

        r = row.iloc[0]
        return PitcherStatsRaw(
            external_id=external_id,
            name=str(r.get("Name", "")),
            team_short=str(r.get("Team", "")),
            season=season,
            era=float(r.get("ERA", 4.50)),
            whip=float(r.get("WHIP", 1.30)),
            k9=float(r.get("K/9", 8.0)),
            ip=float(r.get("IP", 0)),
            wins=int(r.get("W", 0)),
            losses=int(r.get("L", 0)),
        )

    def _get_team_id(self, team_short: str) -> Optional[int]:
        """팀 약자 → pybaseball team id 매핑"""
        # pybaseball은 팀 이름/도시 기반 id 사용
        mapping = {
            "ARI": 109, "ATL": 144, "BAL": 110, "BOS": 111, "CHC": 112,
            "CWS": 145, "CIN": 113, "CLE": 114, "COL": 115, "DET": 116,
            "HOU": 117, "KC": 118, "LAA": 108, "LAD": 119, "MIA": 146,
            "MIL": 158, "MIN": 142, "NYM": 121, "NYY": 147, "OAK": 133,
            "PHI": 143, "PIT": 134, "SD": 135, "SF": 137, "SEA": 136,
            "STL": 138, "TB": 139, "TEX": 140, "TOR": 141, "WSH": 120,
        }
        return mapping.get(team_short)

    def _cache_path(self, key: str) -> Path:
        return CACHE_DIR / f"{key}.parquet"

    def _load_cache(self, key: str) -> Optional[pd.DataFrame]:
        path = self._cache_path(key)
        if path.exists():
            try:
                return pd.read_parquet(path)
            except Exception:
                path.unlink(missing_ok=True)
        return None

    def _save_cache(self, df: pd.DataFrame, key: str) -> None:
        try:
            self._cache_path(key).parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(self._cache_path(key), index=False)
        except Exception as e:
            logger.warning(f"캐시 저장 실패 ({key}): {e}")
