"""
MLB 선발투수 및 타순 수집기
statsapi를 사용하여 probable pitchers와 boxscore 라인업 수집
"""
import logging
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


def _get_pitcher_name(pitcher_id: int) -> Optional[str]:
    """statsapi로 투수 이름 조회"""
    try:
        import statsapi
        data = statsapi.get("person", {"personId": pitcher_id})
        return data.get("people", [{}])[0].get("fullName")
    except Exception:
        return None


async def fetch_mlb_lineup(game_pk: str) -> Optional[dict]:
    """
    MLB 경기 라인업 수집 (statsapi boxscore 기반)
    경기 시작 후에는 실제 타순, 이전에는 probable pitchers만 반환
    Returns: {home_starter, away_starter, home_lineup, away_lineup, confirmed}
    """
    import asyncio
    return await asyncio.to_thread(_fetch_mlb_lineup_sync, game_pk)


def _fetch_mlb_lineup_sync(game_pk: str) -> Optional[dict]:
    try:
        import statsapi

        # boxscore 조회 (경기 시작 후 실제 라인업)
        box = statsapi.get("game_boxscore", {"gamePk": game_pk})
        teams = box.get("teams", {})
        home = teams.get("home", {})
        away = teams.get("away", {})

        home_players = home.get("players", {})
        away_players = away.get("players", {})
        home_batting_order = home.get("battingOrder", [])
        away_batting_order = away.get("battingOrder", [])

        # 타순 파싱
        def parse_lineup(players: dict, batting_order: list) -> list:
            lineup = []
            for i, pid in enumerate(batting_order):
                key = f"ID{pid}"
                player = players.get(key, {})
                person = player.get("person", {})
                pos = player.get("position", {})
                lineup.append({
                    "order": i + 1,
                    "name": person.get("fullName", ""),
                    "position": pos.get("abbreviation", ""),
                })
            return lineup

        home_lineup = parse_lineup(home_players, home_batting_order)
        away_lineup = parse_lineup(away_players, away_batting_order)

        # 선발투수 파싱
        def get_starter(players: dict) -> Optional[str]:
            for key, player in players.items():
                game_status = player.get("gameStatus", {})
                stats = player.get("stats", {})
                pitching = stats.get("pitching", {})
                # 선발투수: gamesStarted=1 이거나 gameStarted 상태
                if (game_status.get("isCurrentPitcher") or pitching.get("gamesStarted", 0) == 1):
                    return player.get("person", {}).get("fullName")
            return None

        # pitchingOrder로 선발 찾기
        def get_starter_from_order(players: dict) -> Optional[str]:
            for key, player in players.items():
                if player.get("stats", {}).get("pitching", {}).get("gamesStarted", 0) == 1:
                    return player.get("person", {}).get("fullName")
            return None

        home_starter = get_starter_from_order(home_players)
        away_starter = get_starter_from_order(away_players)

        # boxscore에 라인업이 없으면 probable pitchers 시도
        if not home_lineup and not away_lineup:
            return _fetch_probable_pitchers_sync(game_pk)

        confirmed = bool(home_lineup and away_lineup)
        return {
            "home_starter": home_starter,
            "away_starter": away_starter,
            "home_lineup": home_lineup,
            "away_lineup": away_lineup,
            "confirmed": confirmed,
            "source": "mlb_boxscore",
        }

    except Exception as e:
        logger.debug(f"MLB boxscore 수집 실패 ({game_pk}): {e}")
        return _fetch_probable_pitchers_sync(game_pk)


def _fetch_probable_pitchers_sync(game_pk: str) -> Optional[dict]:
    """probable pitchers만 수집 (경기 전)"""
    try:
        import statsapi

        data = statsapi.get("game", {"gamePk": game_pk})
        game_data = data.get("gameData", {})
        probable = game_data.get("probablePitchers", {})

        home_pitcher = probable.get("home", {})
        away_pitcher = probable.get("away", {})

        home_starter = home_pitcher.get("fullName")
        away_starter = away_pitcher.get("fullName")

        if not home_starter and not away_starter:
            return None

        return {
            "home_starter": home_starter,
            "away_starter": away_starter,
            "home_lineup": [],
            "away_lineup": [],
            "confirmed": bool(home_starter and away_starter),
            "source": "mlb_probable",
        }
    except Exception as e:
        logger.debug(f"MLB probable pitchers 수집 실패 ({game_pk}): {e}")
        return None


async def fetch_mlb_schedule_starters(target_date: date) -> dict[str, tuple[Optional[str], Optional[str]]]:
    """
    특정 날짜 MLB 경기 선발투수 일정 수집
    Returns: {game_pk: (home_starter_name, away_starter_name)}
    """
    import asyncio
    return await asyncio.to_thread(_fetch_schedule_starters_sync, target_date)


def _fetch_schedule_starters_sync(target_date: date) -> dict[str, tuple[Optional[str], Optional[str]]]:
    try:
        import statsapi

        data = statsapi.schedule(
            date=target_date.strftime("%m/%d/%Y"),
            sportId=1,
        )
        result = {}
        for game in data:
            game_type = game.get("game_type", "R")
            if game_type not in {"R", "F", "D", "L", "W", "P"}:
                continue
            game_pk = str(game.get("game_id", ""))
            home_starter = game.get("home_probable_pitcher") or None
            away_starter = game.get("away_probable_pitcher") or None
            if game_pk:
                result[game_pk] = (home_starter, away_starter)
        return result
    except Exception as e:
        logger.error(f"MLB 선발 일정 수집 실패 ({target_date}): {e}")
        return {}
