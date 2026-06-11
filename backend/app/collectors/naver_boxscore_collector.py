"""
Naver KBO 경기 종료 후 박스스코어(타자/투수 기록) 수집
statiz 대신 자체 DB 집계의 원천 데이터
"""
import logging
import time
from typing import Optional

import httpx

from app.collectors.naver_lineup_collector import NAVER_HEADERS, _naver_game_id

logger = logging.getLogger(__name__)


def _safe_int(val, default: int = 0) -> int:
    if val is None or val == "" or val == "-":
        return default
    try:
        return int(float(str(val).replace(",", "")))
    except (TypeError, ValueError):
        return default


def _parse_ip(val) -> float:
    if val is None or val == "" or val == "-":
        return 0.0
    s = str(val).strip()
    try:
        if " " in s and "/" in s:
            whole, frac = s.split(None, 1)
            num, den = frac.split("/")
            return float(whole) + float(num) / float(den)
        return float(s.replace(",", ""))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _pick(d: dict, *keys: str, default=0):
    for k in keys:
        if k in d and d[k] not in (None, "", "-"):
            return d[k]
    return default


def _parse_batter_row(b: dict) -> dict:
    ab = _safe_int(_pick(b, "ab", "AB", "atBat"))
    hits = _safe_int(_pick(b, "hit", "hits", "H", "h"))
    bb = _safe_int(_pick(b, "bb", "BB", "baseOnBalls", "walk"))
    so = _safe_int(_pick(b, "so", "SO", "kk", "strikeOut"))
    hbp = _safe_int(_pick(b, "hbp", "HBP"))
    sf = _safe_int(_pick(b, "sf", "SF", "sacrificeFly"))
    doubles = _safe_int(_pick(b, "double", "2b", "2B", "hit2"))
    triples = _safe_int(_pick(b, "triple", "3b", "3B", "hit3"))
    hr = _safe_int(_pick(b, "hr", "HR", "homeRun"))
    pa = _safe_int(_pick(b, "pa", "PA", "plateAppearances"))
    if pa <= 0:
        pa = ab + bb + hbp + sf
    return {
        "name": (b.get("name") or b.get("playerName") or "").strip(),
        "order": _safe_int(b.get("batOrder") or b.get("order"), 0),
        "position": b.get("pos") or b.get("posName") or "",
        "pa": pa,
        "ab": ab,
        "hits": hits,
        "doubles": doubles,
        "triples": triples,
        "hr": hr,
        "bb": bb,
        "so": so,
        "hbp": hbp,
        "sf": sf,
    }


def _parse_pitcher_row(p: dict, is_starter: bool) -> dict:
    ip = _parse_ip(_pick(p, "inn", "ip", "IP", "inning"))
    er = _safe_int(_pick(p, "er", "ER", "earnedRun"))
    hits_allowed = _safe_int(_pick(p, "hit", "hits", "H", "h"))
    bb_allowed = _safe_int(_pick(p, "bb", "BB", "baseOnBalls"))
    so = _safe_int(_pick(p, "so", "SO", "kk", "strikeOut"))
    return {
        "name": (p.get("name") or p.get("playerName") or "").strip(),
        "is_starter": is_starter,
        "ip": ip,
        "er": er,
        "hits_allowed": hits_allowed,
        "bb_allowed": bb_allowed,
        "so_pitched": so,
    }


def fetch_boxscore_sync(kbo_game_id: str) -> Optional[dict]:
    """KBO external_game_id → Naver record 박스스코어

    Returns:
        {
          "home_starter", "away_starter",
          "home_batters": [...], "away_batters": [...],
          "home_pitchers": [...], "away_pitchers": [...],
        }
    """
    naver_id = _naver_game_id(kbo_game_id)
    try:
        time.sleep(0.3)
        resp = httpx.get(
            f"https://api-gw.sports.naver.com/schedule/games/{naver_id}/record",
            headers=NAVER_HEADERS,
            timeout=15,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        record = resp.json().get("result", {}).get("recordData", {})
        if not record:
            return None

        pitchers = record.get("pitchersBoxscore", {}) or {}
        batters = record.get("battersBoxscore", {}) or {}
        home_pitchers_raw = pitchers.get("home") or []
        away_pitchers_raw = pitchers.get("away") or []
        home_batters_raw = batters.get("home") or []
        away_batters_raw = batters.get("away") or []

        if not home_batters_raw and not away_batters_raw and not home_pitchers_raw:
            return None

        home_starter = home_pitchers_raw[0].get("name") if home_pitchers_raw else None
        away_starter = away_pitchers_raw[0].get("name") if away_pitchers_raw else None

        home_batters = [_parse_batter_row(b) for b in home_batters_raw if b.get("name")]
        away_batters = [_parse_batter_row(b) for b in away_batters_raw if b.get("name")]
        home_pitchers = [
            _parse_pitcher_row(p, is_starter=(i == 0))
            for i, p in enumerate(home_pitchers_raw) if p.get("name")
        ]
        away_pitchers = [
            _parse_pitcher_row(p, is_starter=(i == 0))
            for i, p in enumerate(away_pitchers_raw) if p.get("name")
        ]

        logger.info(
            f"Naver 박스스코어 ({naver_id}): "
            f"home 타자 {len(home_batters)} 투수 {len(home_pitchers)}, "
            f"away 타자 {len(away_batters)} 투수 {len(away_pitchers)}"
        )
        return {
            "home_starter": home_starter,
            "away_starter": away_starter,
            "home_batters": home_batters,
            "away_batters": away_batters,
            "home_pitchers": home_pitchers,
            "away_pitchers": away_pitchers,
            "source": "naver_record",
        }
    except Exception as e:
        logger.warning(f"Naver 박스스코어 수집 실패 ({kbo_game_id}): {e}")
        return None
