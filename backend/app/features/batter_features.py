"""
타선 피처 계산
팀 타선 OPS 평균, wRC+, 좌완 투수 상대 OPS, 삼진율
KBO: statiz.co.kr 스크래핑 (로그인 필요)
MLB: pybaseball batting_stats()
"""
import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_KBO_BATTER_CACHE: dict[int, tuple[float, dict[tuple[str, str], float]]] = {}
_MLB_BATTER_CACHE: dict[int, tuple[float, dict[str, float]]] = {}
_BATTER_CACHE_TTL = 6 * 3600  # 6시간

# 리그 평균 타격 지표 (스탯 수집 실패 시 폴백)
MLB_BATTING_AVG = {"ops": 0.728, "wrc_plus": 100, "k_rate": 0.222}
KBO_BATTING_AVG = {"ops": 0.740, "wrc_plus": 100, "k_rate": 0.200}


async def _get_kbo_team_batting_split(team_id: int, season: int, split: str, db: AsyncSession) -> Optional[float]:
    """KBO 팀 타선 vs LHP/RHP 스플릿 OPS 조회 ('vs_lhp' or 'vs_rhp')"""
    try:
        from sqlalchemy import select, and_
        from app.models import Team
        from app.models.kbo_stats import KboTeamBattingSplitStat

        team_result = await db.execute(select(Team).where(Team.id == team_id))
        team = team_result.scalar_one_or_none()
        if not team:
            return None

        for s in [season, season - 1]:
            row = (await db.execute(
                select(KboTeamBattingSplitStat).where(
                    and_(
                        KboTeamBattingSplitStat.team_short == team.short_name,
                        KboTeamBattingSplitStat.season == s,
                        KboTeamBattingSplitStat.split == split,
                    )
                )
            )).scalar_one_or_none()
            if row:
                return row.ops
        return None
    except Exception as e:
        logger.debug(f"KBO 타선 스플릿 OPS DB 조회 실패 (team_id={team_id}, split={split}): {e}")
        return None


async def _get_kbo_team_batting(team_id: int, season: int, db: AsyncSession) -> Optional[dict]:
    """KBO 팀 타선 스탯을 DB에서 조회 (로컬에서 업로드된 statiz 스탯)
    현 시즌 없으면 직전 시즌 폴백
    """
    try:
        from sqlalchemy import select, and_
        from app.models import Team
        from app.models.kbo_stats import KboTeamBattingStat

        team_result = await db.execute(select(Team).where(Team.id == team_id))
        team = team_result.scalar_one_or_none()
        if not team:
            return None

        for s in [season, season - 1]:
            row = (await db.execute(
                select(KboTeamBattingStat).where(
                    and_(KboTeamBattingStat.team_short == team.short_name, KboTeamBattingStat.season == s)
                )
            )).scalar_one_or_none()
            if row:
                return {"ops": row.ops, "wrc_plus": row.wrc_plus, "k_rate": row.k_rate}
        return None
    except Exception as e:
        logger.debug(f"KBO 타선 스탯 DB 조회 실패 (team_id={team_id}): {e}")
        return None


async def _get_mlb_team_batting(team_id: int, season: int, db: AsyncSession) -> Optional[dict]:
    """MLB 팀 타선 스탯 DB 조회 (mlb_team_batting_stats)"""
    try:
        from sqlalchemy import select, and_
        from app.models import Team
        from app.models.mlb_stats import MlbTeamBattingStat

        team_result = await db.execute(select(Team).where(Team.id == team_id))
        team = team_result.scalar_one_or_none()
        if not team:
            return None

        for s in [season, season - 1]:
            row = (await db.execute(
                select(MlbTeamBattingStat).where(
                    and_(MlbTeamBattingStat.team_short == team.short_name, MlbTeamBattingStat.season == s)
                )
            )).scalar_one_or_none()
            if row:
                return {"ops": row.ops, "wrc_plus": row.wrc_plus, "k_rate": row.k_rate, "bb_rate": row.bb_rate}
        return None
    except Exception as e:
        logger.debug(f"MLB 타선 스탯 DB 조회 실패 (team_id={team_id}): {e}")
        return None


async def _get_mlb_team_batting_split(team_id: int, season: int, split: str, db: AsyncSession) -> Optional[float]:
    """MLB 팀 타선 vs LHP/RHP 스플릿 OPS 조회 ('vs_lhp' or 'vs_rhp')"""
    try:
        from sqlalchemy import select, and_
        from app.models import Team
        from app.models.mlb_stats import MlbTeamBattingSplitStat

        team_result = await db.execute(select(Team).where(Team.id == team_id))
        team = team_result.scalar_one_or_none()
        if not team:
            return None

        for s in [season, season - 1]:
            row = (await db.execute(
                select(MlbTeamBattingSplitStat).where(
                    and_(
                        MlbTeamBattingSplitStat.team_short == team.short_name,
                        MlbTeamBattingSplitStat.season == s,
                        MlbTeamBattingSplitStat.split == split,
                    )
                )
            )).scalar_one_or_none()
            if row:
                return row.ops
        return None
    except Exception as e:
        logger.debug(f"MLB 타선 스플릿 OPS DB 조회 실패 (team_id={team_id}, split={split}): {e}")
        return None


async def get_lineup_features(
    db: AsyncSession,
    team_id: int,
    league: str,
    season: int,
    opponent_starter_throws: Optional[str] = None,
) -> dict:
    """팀 타선 피처 반환"""
    avg = MLB_BATTING_AVG if league == "MLB" else KBO_BATTING_AVG

    real_stats = None
    if league == "KBO":
        real_stats = await _get_kbo_team_batting(team_id, season, db)
    elif league == "MLB":
        real_stats = await _get_mlb_team_batting(team_id, season, db)

    if real_stats:
        ops      = real_stats["ops"]
        wrc_plus = real_stats.get("wrc_plus") or avg["wrc_plus"]
        k_rate   = real_stats["k_rate"]
        imputed  = False
    else:
        ops      = avg["ops"]
        wrc_plus = avg["wrc_plus"]
        k_rate   = avg["k_rate"]
        imputed  = True

    # 실제 좌우 스플릿 OPS 조회 (없으면 고정 보정 폴백)
    split_ops_vs_lhp: Optional[float] = None
    split_ops_vs_rhp: Optional[float] = None
    if league == "KBO":
        split_ops_vs_lhp = await _get_kbo_team_batting_split(team_id, season, "vs_lhp", db)
        split_ops_vs_rhp = await _get_kbo_team_batting_split(team_id, season, "vs_rhp", db)
    elif league == "MLB":
        split_ops_vs_lhp = await _get_mlb_team_batting_split(team_id, season, "vs_lhp", db)
        split_ops_vs_rhp = await _get_mlb_team_batting_split(team_id, season, "vs_rhp", db)

    lhp_ops = split_ops_vs_lhp if split_ops_vs_lhp is not None else ops * 0.97
    rhp_ops = split_ops_vs_rhp if split_ops_vs_rhp is not None else ops * 1.02

    # 상대 투수 투구 방향에 따라 유효 OPS 결정
    if opponent_starter_throws == "L":
        effective_ops = lhp_ops
    else:
        effective_ops = rhp_ops

    return {
        "lineup_ops_mean":      ops,
        "lineup_wrc_plus":      wrc_plus,
        "lineup_k_rate":        k_rate,
        "lineup_vs_lhp_ops":    lhp_ops,
        "lineup_vs_rhp_ops":    rhp_ops,
        "effective_ops":        effective_ops,
        "is_lineup_imputed":    imputed,
    }


def _normalize_batter_name(name: str) -> str:
    """한글/영문 타자명 정규화 (공백·특수문자 제거)"""
    if not name:
        return ""
    return re.sub(r"[\s·\-]", "", name.strip())


async def _load_kbo_batter_ops_map(season: int) -> dict[tuple[str, str], float]:
    """KBO 시즌 타자 OPS 맵 — (정규화이름, 팀약어) → OPS"""
    now = time.time()
    cached = _KBO_BATTER_CACHE.get(season)
    if cached and (now - cached[0]) < _BATTER_CACHE_TTL:
        return cached[1]

    from app.collectors.kbo_collector import KBOCollector
    col = KBOCollector()
    batters = await col.fetch_batting_stats_season(season)

    ops_map: dict[tuple[str, str], float] = {}
    for b in batters:
        key = (_normalize_batter_name(b.get("name", "")), b.get("team_short", ""))
        if key[0] and b.get("ops") is not None:
            ops_map[key] = float(b["ops"])

    _KBO_BATTER_CACHE[season] = (now, ops_map)
    return ops_map


def _load_mlb_batter_ops_map_sync(season: int) -> dict[str, float]:
    """MLB 시즌 타자 OPS 맵 — 정규화이름 → OPS (JSON 캐시)"""
    cache_path = Path(f"data/raw/mlb_batting_ops_{season}.json")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    current_year = time.localtime().tm_year
    ttl = 24 * 3600 if season >= current_year else None

    if cache_path.exists():
        stale = ttl is not None and (time.time() - cache_path.stat().st_mtime) > ttl
        if not stale:
            try:
                return {k: float(v) for k, v in json.loads(cache_path.read_text(encoding="utf-8")).items()}
            except Exception:
                cache_path.unlink(missing_ok=True)

    ops_map: dict[str, float] = {}
    try:
        import pybaseball as pyb
        pyb.cache.enable()
        df = pyb.batting_stats(season, qual=1)
        if df is not None and not df.empty:
            name_col = "Name" if "Name" in df.columns else "name"
            ops_col = "OPS" if "OPS" in df.columns else "ops"
            for _, row in df.iterrows():
                norm = _normalize_batter_name(str(row.get(name_col, "")))
                try:
                    ops = float(row.get(ops_col))
                except (TypeError, ValueError):
                    continue
                if norm:
                    ops_map[norm] = ops
        cache_path.write_text(json.dumps(ops_map, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.debug(f"MLB 타자 OPS 수집 실패 ({season}): {e}")

    return ops_map


async def _load_mlb_batter_ops_map(season: int) -> dict[str, float]:
    now = time.time()
    cached = _MLB_BATTER_CACHE.get(season)
    if cached and (now - cached[0]) < _BATTER_CACHE_TTL:
        return cached[1]
    ops_map = await asyncio.to_thread(_load_mlb_batter_ops_map_sync, season)
    _MLB_BATTER_CACHE[season] = (now, ops_map)
    return ops_map


async def _lookup_batter_ops(
    name: str,
    league: str,
    season: int,
    team_short: str,
    kbo_map: dict[tuple[str, str], float],
    mlb_map: dict[str, float],
) -> Optional[float]:
    norm = _normalize_batter_name(name)
    if not norm:
        return None
    if league == "KBO":
        for s in [season, season - 1]:
            if s == season:
                m = kbo_map
            else:
                m = await _load_kbo_batter_ops_map(s)
            ops = m.get((norm, team_short)) or m.get((norm, ""))
            if ops is None:
                for (n, _), v in m.items():
                    if n == norm or (len(norm) >= 2 and norm in n) or (len(n) >= 2 and n in norm):
                        ops = v
                        break
            if ops is not None:
                return ops
        return None
    ops = mlb_map.get(norm)
    if ops is not None:
        return ops
    for n, v in mlb_map.items():
        if norm in n or n in norm:
            return v
    return None


async def get_roster_lineup_features(
    lineup_json: Optional[list],
    league: str,
    season: int,
    team_short: str,
    prefix: str,
    team_fallback_ops: Optional[float] = None,
) -> dict:
    """타순 1~9번 개별 OPS + 라인업 매칭률 피처

    lineup_json 항목: {"order": 1, "name": "...", "position": "..."}
    """
    result: dict = {}
    slots: list[Optional[float]] = [None] * 9

    kbo_map: dict = {}
    mlb_map: dict = {}
    if league == "KBO":
        kbo_map = await _load_kbo_batter_ops_map(season)
    elif league == "MLB":
        mlb_map = await _load_mlb_batter_ops_map(season)

    entries = lineup_json or []
    by_order: dict[int, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        order = entry.get("order")
        name = entry.get("name") or entry.get("player_name")
        if order is None or not name:
            continue
        try:
            by_order[int(order)] = str(name)
        except (TypeError, ValueError):
            continue

    known = 0
    for i in range(1, 10):
        name = by_order.get(i)
        ops = None
        if name:
            ops = await _lookup_batter_ops(name, league, season, team_short, kbo_map, mlb_map)
            if ops is not None:
                known += 1
            elif team_fallback_ops is not None:
                ops = team_fallback_ops
        slots[i - 1] = ops
        result[f"{prefix}_lineup_ops_{i}"] = ops

    known_ops = [s for s in slots if s is not None]
    result[f"{prefix}_lineup_known_pct"] = known / 9.0
    result[f"{prefix}_lineup_player_ops_mean"] = (
        sum(known_ops) / len(known_ops) if known_ops else team_fallback_ops
    )
    return result
