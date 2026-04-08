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
    """
    MLB 경기 타순 수집 — live feed 기준 (경기 전 라인업 제출 후 + 경기 중/후 모두 작동)
    타순 없으면 probable pitchers만 반환
    """
    try:
        import httpx

        resp = httpx.get(
            f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live",
            timeout=15,
        )
        if resp.status_code != 200:
            return _fetch_probable_pitchers_sync(game_pk)

        data = resp.json()
        box = data.get("liveData", {}).get("boxscore", {})
        teams = box.get("teams", {})

        def parse_side(side: str) -> tuple[list, Optional[str]]:
            t = teams.get(side, {})
            players = t.get("players", {})
            batting_order = t.get("battingOrder", [])
            pitchers_order = t.get("pitchers", [])

            lineup = []
            for i, pid in enumerate(batting_order):
                p = players.get(f"ID{pid}", {})
                lineup.append({
                    "order": i + 1,
                    "name": p.get("person", {}).get("fullName", ""),
                    "position": p.get("position", {}).get("abbreviation", ""),
                })

            # 선발투수: pitchers 리스트 첫번째 OR gamesStarted=1
            starter = None
            if pitchers_order:
                sp = players.get(f"ID{pitchers_order[0]}", {})
                starter = sp.get("person", {}).get("fullName")
            if not starter:
                for p in players.values():
                    if p.get("stats", {}).get("pitching", {}).get("gamesStarted", 0) == 1:
                        starter = p.get("person", {}).get("fullName")
                        break

            return lineup, starter

        home_lineup, home_starter = parse_side("home")
        away_lineup, away_starter = parse_side("away")

        if not home_lineup and not away_lineup:
            # 타순 미제출 — probable pitchers만 반환
            return _fetch_probable_pitchers_sync(game_pk)

        return {
            "home_starter": home_starter,
            "away_starter": away_starter,
            "home_lineup": home_lineup,
            "away_lineup": away_lineup,
            "confirmed": bool(home_lineup and away_lineup),
            "source": "mlb_live",
        }

    except Exception as e:
        logger.debug(f"MLB live feed 수집 실패 ({game_pk}): {e}")
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
