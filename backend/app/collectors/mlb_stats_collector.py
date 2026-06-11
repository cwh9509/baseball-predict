"""
MLB 시즌 스탯 수집기 — pybaseball(FanGraphs) 기반
2024-2025 시즌 투수/타자/불펜/구장 데이터 자동 수집 및 DB upsert

주요 기능:
  - 투수 개인 스탯: ERA, FIP, WHIP, K/9, BB/9, IP, GS (FanGraphs)
  - 투구 방향(L/R): MLB StatsAPI player lookup
  - 팀 불펜 집계: GS/G < 0.3 인 투수 IP 가중 평균
  - 팀 타선 집계: FanGraphs 팀별 OPS, wRC+, K%, BB%
  - 타선 스플릿: Statcast pitch-level 데이터 → vs LHP / vs RHP (실측)
                실측 실패 시 팀 OPS 기반 보정값 저장
"""
import asyncio
import json
import logging
import os
import time
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = Path(os.environ.get("DATA_RAW_PATH", "data/raw"))

# FanGraphs 팀 약자 → 내부 약자 매핑 (다른 경우만)
_FG_TEAM_MAP: dict[str, str] = {
    "KCR": "KC",
    "SDP": "SD",
    "SFG": "SF",
    "TBR": "TB",
    "WSN": "WSH",
    "ATH": "OAK",   # Oakland Athletics 새크라멘토 이전 후 FanGraphs 표기
    "ANA": "LAA",
}

# FanGraphs 팀 이름(전체) → 약자 (batting_stats에서 사용)
_FG_TEAM_NAME_MAP: dict[str, str] = {
    "Diamondbacks": "ARI", "Braves": "ATL", "Orioles": "BAL", "Red Sox": "BOS",
    "Cubs": "CHC", "White Sox": "CWS", "Reds": "CIN", "Guardians": "CLE",
    "Rockies": "COL", "Tigers": "DET", "Astros": "HOU", "Royals": "KC",
    "Angels": "LAA", "Dodgers": "LAD", "Marlins": "MIA", "Brewers": "MIL",
    "Twins": "MIN", "Mets": "NYM", "Yankees": "NYY", "Athletics": "OAK",
    "Phillies": "PHI", "Pirates": "PIT", "Padres": "SD", "Giants": "SF",
    "Mariners": "SEA", "Cardinals": "STL", "Rays": "TB", "Rangers": "TEX",
    "Blue Jays": "TOR", "Nationals": "WSH",
}

# 내부 약자 → MLB StatsAPI team ID
_TEAM_MLBAM_IDS: dict[str, int] = {
    "ARI": 109, "ATL": 144, "BAL": 110, "BOS": 111, "CHC": 112,
    "CWS": 145, "CIN": 113, "CLE": 114, "COL": 115, "DET": 116,
    "HOU": 117, "KC": 118, "LAA": 108, "LAD": 119, "MIA": 146,
    "MIL": 158, "MIN": 142, "NYM": 121, "NYY": 147, "OAK": 133,
    "PHI": 143, "PIT": 134, "SD": 135, "SF": 137, "SEA": 136,
    "STL": 138, "TB": 139, "TEX": 140, "TOR": 141, "WSH": 120,
}

_STATSAPI_CACHE_TTL = 24 * 3600


def _normalize_team(team_raw: str) -> str:
    """FanGraphs 팀 표기 → 내부 약자 정규화"""
    if not team_raw:
        return "UNK"
    t = str(team_raw).strip()
    if t in _FG_TEAM_MAP:
        return _FG_TEAM_MAP[t]
    # 이미 내부 약자인 경우
    known = {"ARI","ATL","BAL","BOS","CHC","CWS","CIN","CLE","COL","DET",
             "HOU","KC","LAA","LAD","MIA","MIL","MIN","NYM","NYY","OAK",
             "PHI","PIT","SD","SF","SEA","STL","TB","TEX","TOR","WSH"}
    if t in known:
        return t
    # 닉네임으로 매핑 시도
    for nickname, short in _FG_TEAM_NAME_MAP.items():
        if nickname.lower() in t.lower():
            return short
    return t


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.parquet"


def _load_cache(key: str) -> Optional[pd.DataFrame]:
    p = _cache_path(key)
    if p.exists():
        try:
            return pd.read_parquet(p)
        except Exception:
            p.unlink(missing_ok=True)
    return None


def _save_cache(df: pd.DataFrame, key: str) -> None:
    try:
        _cache_path(key).parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(_cache_path(key), index=False)
    except Exception as e:
        logger.warning(f"캐시 저장 실패 ({key}): {e}")


def _json_cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def _load_json_cache(key: str, ttl_sec: Optional[int] = _STATSAPI_CACHE_TTL) -> Optional[list]:
    p = _json_cache_path(key)
    if not p.exists():
        return None
    if ttl_sec is not None and (time.time() - p.stat().st_mtime) > ttl_sec:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        p.unlink(missing_ok=True)
        return None


def _save_json_cache(key: str, data: list) -> None:
    try:
        _json_cache_path(key).parent.mkdir(parents=True, exist_ok=True)
        _json_cache_path(key).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning(f"JSON 캐시 저장 실패 ({key}): {e}")


def _mlb_statsapi_get(params: dict) -> dict:
    import statsapi
    return statsapi.get("stats", params)


def _fetch_season_splits_paginated(group: str, season: int) -> list[dict]:
    """MLB StatsAPI 시즌 스탯 전체 페이지 조회 (pitching | hitting)"""
    cache_key = f"statsapi_{group}_{season}"
    cached = _load_json_cache(cache_key)
    if cached is not None:
        logger.info(f"StatsAPI {group} 캐시 사용 (season={season}, {len(cached)}건)")
        return cached

    splits: list[dict] = []
    offset = 0
    limit = 200
    while True:
        data = _mlb_statsapi_get({
            "stats": "season",
            "group": group,
            "season": season,
            "sportId": 1,
            "playerPool": "all",
            "limit": limit,
            "offset": offset,
            "hydrate": "team",
        })
        batch = data.get("stats", [{}])[0].get("splits", [])
        splits.extend(batch)
        if len(batch) < limit:
            break
        offset += limit

    _save_json_cache(cache_key, splits)
    logger.info(f"StatsAPI {group} 수집 완료 (season={season}, {len(splits)}건)")
    return splits


# ── 투수 스탯 ──────────────────────────────────────────────────

def _fetch_pitching_stats_sync(season: int) -> pd.DataFrame:
    """FanGraphs 투수 리더보드 수집 (qual=0: 최소 이닝 제한 없음)"""
    import pybaseball as pb

    cache_key = f"fg_pitching_{season}"
    cached = _load_cache(cache_key)
    if cached is not None:
        return cached

    try:
        pb.cache.enable()
        df = pb.pitching_stats(season, season, qual=0)
        if df is None or df.empty:
            logger.warning(f"FanGraphs 투수 스탯 없음 (season={season})")
            return pd.DataFrame()
        _save_cache(df, cache_key)
        return df
    except Exception as e:
        logger.error(f"FanGraphs 투수 스탯 수집 실패 (season={season}): {e}")
        return pd.DataFrame()


def _get_pitcher_handedness_batch(mlbam_ids: list[int]) -> dict[int, str]:
    """MLB StatsAPI로 선수 투구 방향 일괄 조회 (mlbam_id → "L"/"R")"""
    import statsapi

    result: dict[int, str] = {}
    # StatsAPI는 최대 400개 ID를 한 번에 처리 가능
    chunk_size = 200
    for i in range(0, len(mlbam_ids), chunk_size):
        chunk = mlbam_ids[i:i + chunk_size]
        try:
            ids_str = ",".join(str(x) for x in chunk)
            data = statsapi.get("people", {"personIds": ids_str, "hydrate": "currentTeam"})
            for person in data.get("people", []):
                pid = person.get("id")
                throws = person.get("pitchHand", {}).get("code", "R")
                if pid:
                    result[int(pid)] = throws
        except Exception as e:
            logger.warning(f"선수 투구방향 조회 실패 (chunk {i}): {e}")
    return result


def _get_fg_to_mlbam_map(season: int) -> dict[str, int]:
    """FanGraphs ID → MLBAM ID 매핑 (pybaseball playerid_reverse_lookup 사용)"""
    try:
        import pybaseball as pb
        df_pitch = _load_cache(f"fg_pitching_{season}")
        if df_pitch is None or df_pitch.empty:
            return {}
        fg_ids = df_pitch["IDfg"].dropna().astype(str).tolist()
        if not fg_ids:
            return {}
        id_map = pb.playerid_reverse_lookup(fg_ids, key_type="fangraphs")
        if id_map is None or id_map.empty:
            return {}
        mapping = {}
        for _, row in id_map.iterrows():
            fg = str(row.get("key_fangraphs", ""))
            mlbam = row.get("key_mlbam")
            if fg and pd.notna(mlbam):
                mapping[fg] = int(mlbam)
        return mapping
    except Exception as e:
        logger.warning(f"FanGraphs→MLBAM 매핑 실패: {e}")
        return {}


def _fetch_pitcher_recent_era_batch(mlbam_ids: list[int], season: int) -> dict[int, tuple[float, float]]:
    """statsapi game log로 투수별 최근 3선발 ERA, WHIP 계산
    Returns: {mlbam_id: (recent_era, recent_whip)}
    """
    import statsapi

    result: dict[int, tuple[float, float]] = {}
    for mlbam in mlbam_ids:
        try:
            data = statsapi.get("stats", {
                "personId": mlbam,
                "group": "pitching",
                "stats": "gameLog",
                "season": season,
                "sportId": 1,
            })
            logs = data.get("stats", [{}])[0].get("splits", [])
            # 선발만 필터 (GS=1), 날짜 내림차순
            starts = [s for s in logs if s.get("stat", {}).get("gamesStarted", 0) > 0]
            starts.sort(key=lambda x: x.get("date", ""), reverse=True)
            last3 = starts[:3]
            if not last3:
                continue
            total_er = sum(float(s["stat"].get("earnedRuns", 0)) for s in last3)
            total_ip = sum(float(s["stat"].get("inningsPitched", 0)) for s in last3)
            total_bb_h = sum(
                float(s["stat"].get("hits", 0)) + float(s["stat"].get("baseOnBalls", 0))
                for s in last3
            )
            if total_ip > 0:
                era = round((total_er / total_ip) * 9, 2)
                whip = round(total_bb_h / total_ip, 3)
                result[mlbam] = (era, whip)
        except Exception:
            continue
    return result


def _fetch_pitcher_home_away_era_batch(mlbam_ids: list[int], season: int) -> dict[int, tuple[float, float]]:
    """statsapi splitStats로 투수별 홈/원정 ERA 수집
    Returns: {mlbam_id: (home_era, away_era)}
    """
    import statsapi

    result: dict[int, tuple[float, float]] = {}
    for mlbam in mlbam_ids:
        try:
            data = statsapi.get("stats", {
                "personId": mlbam,
                "group": "pitching",
                "stats": "statSplits",
                "sitCodes": "h,a",
                "season": season,
                "sportId": 1,
            })
            splits = data.get("stats", [{}])[0].get("splits", [])
            home_era = away_era = None
            for sp in splits:
                code = sp.get("split", {}).get("code", "")
                era = sp.get("stat", {}).get("era")
                if code == "h" and era is not None:
                    home_era = float(era)
                elif code == "a" and era is not None:
                    away_era = float(era)
            if home_era is not None and away_era is not None:
                result[mlbam] = (home_era, away_era)
        except Exception:
            continue
    return result


def _extract_pitch_type_cols(row: pd.Series) -> dict:
    """FanGraphs 행에서 구종/구속 컬럼 추출
    FanGraphs 컬럼명: FA% (또는 FF%), SI%, SL%, CH%, vFA (또는 vFF)
    """
    # 패스트볼(4-seam + 2-seam 합산)
    fb_pct = None
    for col in ["FA% (pi)", "FA%", "FF% (pi)", "FF%"]:
        if col in row.index and pd.notna(row.get(col)):
            fb_pct = float(row[col])
            if fb_pct > 1:
                fb_pct = fb_pct / 100.0
            break
    si_pct = None
    for col in ["SI% (pi)", "SI%"]:
        if col in row.index and pd.notna(row.get(col)):
            v = float(row[col])
            si_pct = (v / 100.0) if v > 1 else v
            break
    # 두 값 합산
    if fb_pct is not None and si_pct is not None:
        fastball_pct = round(fb_pct + si_pct, 4)
    elif fb_pct is not None:
        fastball_pct = round(fb_pct, 4)
    elif si_pct is not None:
        fastball_pct = round(si_pct, 4)
    else:
        fastball_pct = None

    # 평균 구속 (mph)
    avg_velocity = None
    for col in ["vFA (pi)", "vFA", "vFF (pi)", "vFF", "Stuff+", "FBv"]:
        if col in row.index and pd.notna(row.get(col)):
            v = float(row[col])
            if 70 < v < 110:   # mph 범위 검증
                avg_velocity = round(v, 1)
                break

    return {"fastball_pct": fastball_pct, "avg_velocity": avg_velocity}


def _enrich_pitcher_records_from_statsapi(
    records: list[dict],
    mlbam_ids: list[int],
    season: int,
) -> None:
    """투구 방향·최근 폼·홈/원정 ERA 보강 (in-place)"""
    if not records or not mlbam_ids:
        return
    unique_ids = list(set(mlbam_ids))
    handedness_map = _get_pitcher_handedness_batch(unique_ids)
    # 선발 위주로 최근/홈원정 조회 (전체 투수 game log 조회는 너무 느림)
    starter_ids = list({
        int(rec["_mlbam_id"])
        for rec in records
        if rec.get("_mlbam_id") and ((rec.get("gs") or 0) >= 1 or (rec.get("ip") or 0) >= 15)
    })
    logger.info(f"최근 3경기 ERA 수집 중 (season={season}, 선발={len(starter_ids)}명)...")
    recent_era_map = _fetch_pitcher_recent_era_batch(starter_ids, season) if starter_ids else {}
    logger.info(f"홈/원정 ERA 수집 중 (season={season}, 선발={len(starter_ids)}명)...")
    home_away_map = _fetch_pitcher_home_away_era_batch(starter_ids, season) if starter_ids else {}
    for rec in records:
        mlbam = rec.pop("_mlbam_id", None)
        if mlbam is None:
            continue
        rec["handedness"] = handedness_map.get(mlbam, rec.get("handedness") or "R")
        recent = recent_era_map.get(mlbam)
        if recent:
            rec["recent_era"] = recent[0]
            rec["recent_whip"] = recent[1]
        home_away = home_away_map.get(mlbam)
        if home_away:
            rec["home_era"] = home_away[0]
            rec["away_era"] = home_away[1]


def _build_pitcher_records_from_statsapi(season: int) -> list[dict]:
    """FanGraphs 실패 시 MLB StatsAPI 시즌 투수 스탯으로 레코드 생성"""
    splits = _fetch_season_splits_paginated("pitching", season)
    records: list[dict] = []
    mlbam_ids: list[int] = []

    for sp in splits:
        stat = sp.get("stat") or {}
        ip = float(stat.get("inningsPitched", 0) or 0)
        if ip < 1:
            continue
        team = sp.get("team") or {}
        abbr = team.get("abbreviation")
        if not abbr:
            continue
        player = sp.get("player") or {}
        mlbam = player.get("id")
        name = player.get("fullName", "")
        if not mlbam or not name:
            continue

        mlbam = int(mlbam)
        mlbam_ids.append(mlbam)
        era = float(stat.get("era", 4.30) or 4.30)
        whip = float(stat.get("whip", 1.28) or 1.28)
        k9 = float(stat.get("strikeoutsPer9Inn", 8.7) or 8.7)
        records.append({
            "season": season,
            "name": name,
            "team_short": _normalize_team(abbr),
            "era": era,
            "fip": None,
            "whip": whip,
            "k9": k9,
            "bb9": _safe_float(stat.get("walksPer9Inn")),
            "ip": ip,
            "gs": int(stat.get("gamesStarted", 0) or 0),
            "g": int(stat.get("gamesPlayed", 0) or 0),
            "handedness": "R",
            "fg_id": None,
            "recent_era": None,
            "recent_whip": None,
            "home_era": None,
            "away_era": None,
            "fastball_pct": None,
            "avg_velocity": None,
            "_mlbam_id": mlbam,
        })

    _enrich_pitcher_records_from_statsapi(records, mlbam_ids, season)
    for rec in records:
        rec.pop("_mlbam_id", None)
    logger.info(f"StatsAPI 투수 레코드 {len(records)}건 생성 (season={season})")
    return records


def build_pitcher_records(season: int) -> list[dict]:
    """투수 스탯 레코드 리스트 생성 (DB upsert용)
    FanGraphs 기본 스탯 + 구종/구속 + statsapi 홈/원정 ERA + 최근 3선발 ERA 포함
    """
    df = _fetch_pitching_stats_sync(season)
    if df.empty:
        logger.warning(f"FanGraphs 투수 스탯 없음 → MLB StatsAPI 폴백 (season={season})")
        return _build_pitcher_records_from_statsapi(season)

    # FanGraphs ID → MLBAM ID 매핑
    fg_to_mlbam = _get_fg_to_mlbam_map(season)
    mlbam_ids = list(set(fg_to_mlbam.values()))

    # 투구 방향 일괄 조회
    handedness_map: dict[int, str] = {}
    if mlbam_ids:
        handedness_map = _get_pitcher_handedness_batch(mlbam_ids)

    # 최근 3선발 ERA/WHIP (statsapi game log)
    logger.info(f"최근 3경기 ERA 수집 중 (season={season}, 투수={len(fg_to_mlbam)}명)...")
    recent_era_map = _fetch_pitcher_recent_era_batch(mlbam_ids, season)

    # 홈/원정 분리 ERA (statsapi statSplits)
    logger.info(f"홈/원정 ERA 수집 중 (season={season})...")
    home_away_map = _fetch_pitcher_home_away_era_batch(mlbam_ids, season)

    records = []
    for _, row in df.iterrows():
        fg_id = str(row.get("IDfg", "")) or None
        mlbam = fg_to_mlbam.get(fg_id) if fg_id else None
        throws = handedness_map.get(mlbam, "R") if mlbam else "R"
        recent = recent_era_map.get(mlbam) if mlbam else None
        home_away = home_away_map.get(mlbam) if mlbam else None

        team_raw = str(row.get("Team", ""))
        if team_raw in ("- - -", "TOT", ""):
            continue

        ip = float(row.get("IP", 0) or 0)
        if ip < 1:
            continue

        gs = int(row.get("GS", 0) or 0)
        g = int(row.get("G", 0) or 0)

        # 구종/구속 추출
        pitch_info = _extract_pitch_type_cols(row)

        records.append({
            "season": season,
            "name": str(row.get("Name", "")),
            "team_short": _normalize_team(team_raw),
            "era": float(row.get("ERA", 4.30) or 4.30),
            "fip": _safe_float(row.get("FIP")),
            "whip": float(row.get("WHIP", 1.28) or 1.28),
            "k9": float(row.get("K/9", 8.7) or 8.7),
            "bb9": _safe_float(row.get("BB/9")),
            "ip": ip,
            "gs": gs,
            "g": g,
            "handedness": throws,
            "fg_id": fg_id,
            # 최근 3선발 폼
            "recent_era": recent[0] if recent else None,
            "recent_whip": recent[1] if recent else None,
            # 홈/원정 ERA
            "home_era": home_away[0] if home_away else None,
            "away_era": home_away[1] if home_away else None,
            # 구종/구속
            "fastball_pct": pitch_info["fastball_pct"],
            "avg_velocity": pitch_info["avg_velocity"],
        })
    return records


def build_bullpen_records(pitcher_records: list[dict]) -> list[dict]:
    """투수 레코드에서 팀별 불펜 집계 (GS/G < 0.3 또는 GS=0인 투수)"""
    from collections import defaultdict

    bullpen_pitchers: dict[tuple, list[dict]] = defaultdict(list)
    for p in pitcher_records:
        g = p.get("g") or 1
        gs = p.get("gs") or 0
        # 순수 불펜: 전체 등판의 30% 미만을 선발로 등판
        if g > 0 and (gs / g) < 0.3:
            key = (p["season"], p["team_short"])
            bullpen_pitchers[key].append(p)

    records = []
    for (season, team_short), pitchers in bullpen_pitchers.items():
        total_ip = sum(p["ip"] for p in pitchers)
        if total_ip < 10:
            continue
        era = sum(p["era"] * p["ip"] for p in pitchers) / total_ip
        whip = sum(p["whip"] * p["ip"] for p in pitchers) / total_ip
        k9_vals = [p["k9"] * p["ip"] for p in pitchers if p.get("k9")]
        k9 = sum(k9_vals) / total_ip if k9_vals else None
        records.append({
            "season": season,
            "team_short": team_short,
            "bullpen_era": round(era, 3),
            "bullpen_whip": round(whip, 3),
            "bullpen_k9": round(k9, 2) if k9 else None,
            "bullpen_count": len(pitchers),
        })
    return records


# ── 타선 스탯 ──────────────────────────────────────────────────

def _fetch_batting_stats_sync(season: int) -> pd.DataFrame:
    """FanGraphs 타자 리더보드 수집 (qual=0)"""
    import pybaseball as pb

    cache_key = f"fg_batting_{season}"
    cached = _load_cache(cache_key)
    if cached is not None:
        return cached

    try:
        pb.cache.enable()
        df = pb.batting_stats(season, season, qual=0)
        if df is None or df.empty:
            return pd.DataFrame()
        _save_cache(df, cache_key)
        return df
    except Exception as e:
        logger.error(f"FanGraphs 타자 스탯 수집 실패 (season={season}): {e}")
        return pd.DataFrame()


def _build_team_batting_records_from_statsapi(season: int) -> list[dict]:
    """MLB StatsAPI 팀 시즌 타격 스탯으로 팀 타선 레코드 생성"""
    records: list[dict] = []
    for team_short, team_id in _TEAM_MLBAM_IDS.items():
        try:
            data = _mlb_statsapi_get({
                "teamId": team_id,
                "group": "hitting",
                "stats": "season",
                "season": season,
                "sportId": 1,
            })
            splits = data.get("stats", [{}])[0].get("splits", [])
            if not splits:
                continue
            stat = splits[0].get("stat", {})
            obp = _safe_float(stat.get("obp"))
            slg = _safe_float(stat.get("slg"))
            pa = int(stat.get("plateAppearances", 0) or 0)
            if obp is None or slg is None or pa < 50:
                continue
            ops = obp + slg
            so = int(stat.get("strikeOuts", 0) or 0)
            bb = int(stat.get("baseOnBalls", 0) or 0)
            avg = _safe_float(stat.get("avg"))
            records.append({
                "season": season,
                "team_short": team_short,
                "ops": round(ops, 4),
                "wrc_plus": round(100 + (ops - 0.728) / 0.728 * 100, 1),
                "k_rate": round(so / pa, 4) if pa else 0.22,
                "bb_rate": round(bb / pa, 4) if pa else None,
                "iso": round(slg - avg, 4) if avg is not None else None,
                "babip": _safe_float(stat.get("babip")),
            })
        except Exception as e:
            logger.debug(f"StatsAPI 팀 타선 실패 ({team_short}): {e}")
    logger.info(f"StatsAPI 팀 타선 레코드 {len(records)}건 생성 (season={season})")
    return records


def build_team_batting_records(season: int) -> list[dict]:
    """개인 타자 스탯을 팀별로 집계하여 팀 타선 레코드 생성"""
    df = _fetch_batting_stats_sync(season)
    if df.empty:
        logger.warning(f"FanGraphs 타자 스탯 없음 → MLB StatsAPI 폴백 (season={season})")
        return _build_team_batting_records_from_statsapi(season)

    # 팀 이적자 제거 (Team이 "- - -" 또는 "TOT")
    df = df[~df["Team"].isin(["- - -", "TOT"])].copy()
    df["team_short"] = df["Team"].apply(_normalize_team)

    # PA 가중 평균으로 팀별 집계
    records = []
    for team_short, grp in df.groupby("team_short"):
        pa_col = "PA" if "PA" in grp.columns else None
        if pa_col is None or grp[pa_col].sum() == 0:
            continue
        total_pa = grp[pa_col].sum()

        def wavg(col: str) -> Optional[float]:
            if col not in grp.columns:
                return None
            vals = grp[col].fillna(0)
            return float((vals * grp[pa_col]).sum() / total_pa)

        # OPS = OBP + SLG
        obp = wavg("OBP")
        slg = wavg("SLG")
        ops = (obp or 0) + (slg or 0) if obp and slg else wavg("OPS")

        k_rate = wavg("K%")  # FanGraphs K% is already a decimal (0-1 range)
        # FanGraphs가 퍼센트(20.5)로 줄 경우 변환
        if k_rate and k_rate > 1:
            k_rate = k_rate / 100.0

        bb_rate = wavg("BB%")
        if bb_rate and bb_rate > 1:
            bb_rate = bb_rate / 100.0

        iso = wavg("ISO")
        babip = wavg("BABIP")
        wrc_plus = wavg("wRC+")

        if ops is None or ops == 0:
            continue

        records.append({
            "season": season,
            "team_short": str(team_short),
            "ops": round(ops, 4),
            "wrc_plus": round(wrc_plus, 1) if wrc_plus else None,
            "k_rate": round(k_rate, 4) if k_rate else 0.22,
            "bb_rate": round(bb_rate, 4) if bb_rate else None,
            "iso": round(iso, 4) if iso else None,
            "babip": round(babip, 4) if babip else None,
        })
    return records


# ── 타선 스플릿 (vs LHP / vs RHP) ──────────────────────────────

def _fetch_statcast_splits_sync(season: int) -> Optional[pd.DataFrame]:
    """Statcast 데이터로 팀별 타선 vs LHP/RHP OPS 집계
    경고: 시즌 전체 데이터 다운로드는 수백 MB이므로 캐시 필수
    실패 시 None 반환 → 추정값 폴백
    """
    import pybaseball as pb

    cache_key = f"statcast_splits_{season}"
    cached = _load_cache(cache_key)
    if cached is not None:
        return cached

    try:
        logger.info(f"Statcast 시즌 데이터 다운로드 중 (season={season}) — 시간이 걸릴 수 있습니다...")
        # 시즌 전체 기간 (4월~10월)
        start = f"{season}-04-01"
        end = f"{season}-10-01"
        df = pb.statcast(start_dt=start, end_dt=end)
        if df is None or df.empty:
            return None

        # 필요한 컬럼만 추출하여 메모리 절약
        keep_cols = ["game_date", "batter", "p_throws", "events",
                     "hit_distance_sc", "launch_speed",
                     "home_team", "away_team", "inning_topbot"]
        df = df[[c for c in keep_cols if c in df.columns]]

        # PA 이벤트만 필터 (타석 결과)
        pa_events = {
            "single", "double", "triple", "home_run", "strikeout", "walk",
            "hit_by_pitch", "field_out", "grounded_into_double_play",
            "double_play", "force_out", "fielders_choice", "fielders_choice_out",
            "sac_fly", "sac_bunt", "catcher_interf", "other_out",
        }
        df = df[df["events"].isin(pa_events)].copy()

        _save_cache(df, cache_key)
        return df
    except Exception as e:
        logger.warning(f"Statcast 데이터 수집 실패 (season={season}): {e}")
        return None


def build_batting_split_records(
    season: int,
    team_batting: list[dict],
    use_statcast: bool = True,
) -> list[dict]:
    """팀별 vs LHP / vs RHP 타선 OPS 스플릿 레코드 생성

    use_statcast=True: Statcast pitch-level 데이터로 실측값 계산
    실패 시: 팀 OPS * 보정 계수로 추정값 생성
    """
    # statsapi 실측값 시도 (Statcast보다 가볍고 정확)
    if use_statcast:
        try:
            api_records = _build_splits_from_statsapi(season)
            if api_records:
                logger.info(f"statsapi 실측 스플릿 {len(api_records)}건 생성 완료")
                return api_records
        except Exception as e:
            logger.warning(f"statsapi 스플릿 계산 실패: {e}")

    # 폴백: 팀 OPS 기반 추정값
    logger.info("Statcast 스플릿 실패 → 팀 OPS 보정값으로 폴백")
    return _build_splits_estimated(season, team_batting)


def _build_splits_from_statsapi(season: int) -> list[dict]:
    """statsapi 팀 타격 split stats로 vs LHP / vs RHP 실측 OPS 수집
    sitCodes: 'vl' = vs left-handed, 'vr' = vs right-handed
    """
    records = []
    for team_short, mlbam_id in _TEAM_MLBAM_IDS.items():
        for sit_code, split_name in [("vl", "vs_lhp"), ("vr", "vs_rhp")]:
            try:
                data = _mlb_statsapi_get({
                    "teamId": mlbam_id,
                    "group": "hitting",
                    "stats": "statSplits",
                    "sitCodes": sit_code,
                    "season": season,
                    "sportId": 1,
                })
                splits = data.get("stats", [{}])[0].get("splits", [])
                if not splits:
                    continue
                stat = splits[0].get("stat", {})
                obp = _safe_float(stat.get("obp"))
                slg = _safe_float(stat.get("slg"))
                pa = int(stat.get("plateAppearances", 0) or 0)
                if obp is None or slg is None:
                    continue
                ops = round(obp + slg, 4)
                records.append({
                    "season": season,
                    "team_short": team_short,
                    "split": split_name,
                    "ops": ops,
                    "wrc_plus": None,   # statsapi는 wRC+ 미제공
                    "pa": pa,
                    "source": "statsapi",
                })
            except Exception as e:
                logger.debug(f"statsapi 스플릿 실패 ({team_short}/{split_name}): {e}")
    return records


def _build_splits_from_statcast(season: int, team_batting: list[dict]) -> list[dict]:
    """statsapi 기반 실측 스플릿으로 교체 (Statcast 폴백은 유지)"""
    return _build_splits_from_statsapi(season)


def _build_splits_estimated(season: int, team_batting: list[dict]) -> list[dict]:
    """팀 OPS 기반 추정 스플릿 생성
    MLB 역사적 패턴:
      vs LHP: 팀 OPS × 0.956 (타자 대부분 우타, 좌완 상대 OPS 감소)
      vs RHP: 팀 OPS × 1.019 (우완 투수가 훨씬 많아 sample 기반 평균에 수렴)
    """
    records = []
    for t in team_batting:
        ops = t["ops"]
        wrc = t.get("wrc_plus")
        records.append({
            "season": season,
            "team_short": t["team_short"],
            "split": "vs_lhp",
            "ops": round(ops * 0.956, 4),
            "wrc_plus": round(wrc * 0.94, 1) if wrc else None,
            "pa": 0,
            "source": "estimated",
        })
        records.append({
            "season": season,
            "team_short": t["team_short"],
            "split": "vs_rhp",
            "ops": round(ops * 1.019, 4),
            "wrc_plus": round(wrc * 1.02, 1) if wrc else None,
            "pa": 0,
            "source": "estimated",
        })
    return records


# ── DB Upsert ──────────────────────────────────────────────────

async def upsert_mlb_stats(season: int, db) -> dict:
    """수집한 MLB 스탯을 DB에 upsert

    Returns: 처리 건수 요약 딕셔너리
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.models.mlb_stats import (
        MlbPitcherStat, MlbTeamBullypenStat,
        MlbTeamBattingStat, MlbTeamBattingSplitStat,
    )

    logger.info(f"MLB 스탯 수집 시작 (season={season})")

    # 1) 투수 스탯 수집 (동기 함수 → 스레드 실행)
    pitcher_records = await asyncio.to_thread(build_pitcher_records, season)
    logger.info(f"투수 레코드 {len(pitcher_records)}건 수집")

    # 2) 불펜 집계
    bullpen_records = build_bullpen_records(pitcher_records)
    logger.info(f"팀 불펜 레코드 {len(bullpen_records)}건 생성")

    # 3) 팀 타선 집계
    batting_records = await asyncio.to_thread(build_team_batting_records, season)
    logger.info(f"팀 타선 레코드 {len(batting_records)}건 수집")

    # 4) 타선 스플릿 (statsapi 실측값 우선)
    split_records = await asyncio.to_thread(
        build_batting_split_records, season, batting_records, True  # statsapi 실측 시도
    )
    logger.info(f"타선 스플릿 레코드 {len(split_records)}건 생성")

    # ── Upsert 투수 ──
    _pitcher_base_keys = (
        "season","name","team_short","era","fip","whip","k9","bb9","ip","gs","g",
        "handedness","fg_id","recent_era","recent_whip","home_era","away_era",
        "fastball_pct","avg_velocity",
    )
    _pitcher_upd_keys = (
        "era","fip","whip","k9","bb9","ip","gs","g","handedness","fg_id",
        "recent_era","recent_whip","home_era","away_era","fastball_pct","avg_velocity",
    )
    for p in pitcher_records:
        vals = {k: p.get(k) for k in _pitcher_base_keys}
        upd = {k: p.get(k) for k in _pitcher_upd_keys}
        stmt = pg_insert(MlbPitcherStat).values(**vals).on_conflict_do_update(
            constraint="uq_mlb_pitcher", set_=upd
        )
        await db.execute(stmt)

    # ── Upsert 불펜 ──
    for b in bullpen_records:
        stmt = pg_insert(MlbTeamBullypenStat).values(**b).on_conflict_do_update(
            constraint="uq_mlb_team_bullpen",
            set_={k: b[k] for k in ("bullpen_era","bullpen_whip","bullpen_k9","bullpen_count")},
        )
        await db.execute(stmt)

    # ── Upsert 팀 타선 ──
    for t in batting_records:
        stmt = pg_insert(MlbTeamBattingStat).values(**t).on_conflict_do_update(
            constraint="uq_mlb_team_batting",
            set_={k: t[k] for k in ("ops","wrc_plus","k_rate","bb_rate","iso","babip")},
        )
        await db.execute(stmt)

    # ── Upsert 타선 스플릿 ──
    for s in split_records:
        stmt = pg_insert(MlbTeamBattingSplitStat).values(**s).on_conflict_do_update(
            constraint="uq_mlb_team_batting_split",
            set_={k: s[k] for k in ("ops","wrc_plus","pa","source")},
        )
        await db.execute(stmt)

    await db.commit()

    summary = {
        "season": season,
        "pitchers": len(pitcher_records),
        "bullpen_teams": len(bullpen_records),
        "batting_teams": len(batting_records),
        "split_records": len(split_records),
    }
    logger.info(f"MLB 스탯 upsert 완료: {summary}")
    return summary


def _safe_float(val) -> Optional[float]:
    try:
        f = float(val)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None
