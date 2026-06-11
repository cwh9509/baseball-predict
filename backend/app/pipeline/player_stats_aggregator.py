"""
KBO 선수 스탯 집계기

전략:
  1. statiz 1회 업로드 → kbo_player_season_stats 시드 (source=statiz)
  2. 경기 종료 후 Naver 박스스코어 → kbo_player_game_stats 저장
  3. 시즌 누적 재계산 → db_game_count 충분하면 source=db (statiz 미참조)
"""
import asyncio
import logging
import re
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import and_, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.naver_boxscore_collector import fetch_boxscore_sync
from app.models import Game, Team
from app.models.kbo_player_stats import KboPlayerGameStat, KboPlayerSeasonStat

logger = logging.getLogger(__name__)

USE_DB_PITCHER_MIN_IP = 5.0
USE_DB_BATTER_MIN_PA = 15
RECENT_PITCHER_DAYS = 14


def _normalize_name(name: str) -> str:
    return re.sub(r"[\s·\-]", "", (name or "").strip())


def _calc_ops(ab, hits, doubles, triples, hr, bb, hbp, sf) -> Optional[float]:
    if ab <= 0 and bb <= 0:
        return None
    denom_obp = ab + bb + hbp + sf
    obp = (hits + bb + hbp) / denom_obp if denom_obp > 0 else None
    slg = (hits + doubles + 2 * triples + 3 * hr) / ab if ab > 0 else None
    if obp is not None and slg is not None:
        return round(obp + slg, 3)
    if ab > 0:
        return round(hits / ab + hits / ab, 3)  # 단순 근사
    return None


def _calc_pitching_rates(ip, er, hits_allowed, bb_allowed, so_pitched) -> tuple[Optional[float], Optional[float], Optional[float]]:
    if ip <= 0:
        return None, None, None
    era = round(er * 9.0 / ip, 2)
    whip = round((hits_allowed + bb_allowed) / ip, 2)
    k9 = round(so_pitched * 9.0 / ip, 2)
    return era, whip, k9


def _recent_pitching_rates(
    lines,
    before_date: date,
    days: int = RECENT_PITCHER_DAYS,
) -> tuple[Optional[float], Optional[float]]:
    """경기 전 기준 최근 N일(또는 최근 3경기) ERA/WHIP"""
    start = before_date - timedelta(days=days)
    recent = [l for l in lines if start <= l.game_date < before_date and l.ip > 0]
    if not recent:
        recent = sorted(
            [l for l in lines if l.game_date < before_date and l.ip > 0],
            key=lambda x: x.game_date,
            reverse=True,
        )[:3]
    if not recent:
        return None, None
    r_ip = sum(l.ip for l in recent)
    r_er = sum(l.er for l in recent)
    r_h = sum(l.hits_allowed for l in recent)
    r_bb = sum(l.bb_allowed for l in recent)
    era, whip, _ = _calc_pitching_rates(r_ip, r_er, r_h, r_bb, 0)
    return era, whip


async def seed_season_from_statiz(db: AsyncSession, season: int) -> dict:
    """statiz 업로드 데이터를 player_season_stats 시드로 복사 (1회성 기준선)"""
    from app.models.kbo_stats import KboPitcherStat

    pitcher_rows = (await db.execute(
        select(KboPitcherStat).where(KboPitcherStat.season == season)
    )).scalars().all()

    p_count = 0
    for p in pitcher_rows:
        vals = dict(
            season=season,
            name=p.name,
            team_short=p.team_short,
            role="pitcher",
            ip=p.ip,
            era=p.era,
            whip=p.whip,
            k9=p.k9,
            gs=p.gs or 0,
            games_pitched=1 if p.ip > 0 else 0,
            handedness=p.handedness,
            recent_era=p.recent_era,
            recent_whip=p.recent_whip,
            db_game_count=0,
            source="statiz",
        )
        stmt = pg_insert(KboPlayerSeasonStat).values(**vals).on_conflict_do_update(
            constraint="uq_kbo_player_season",
            set_={
                "ip": p.ip,
                "era": p.era,
                "whip": p.whip,
                "k9": p.k9,
                "gs": p.gs or 0,
                "handedness": p.handedness,
                "recent_era": p.recent_era,
                "recent_whip": p.recent_whip,
                "source": "statiz",
            },
        )
        await db.execute(stmt)
        p_count += 1

    b_count = 0
    try:
        from app.config import settings
        if not settings.statiz_enabled:
            raise RuntimeError("statiz 비활성 (STATIZ_ENABLED=false)")
        from app.collectors.kbo_collector import KBOCollector
        batters = await KBOCollector().fetch_batting_stats_season(season)
        for b in batters:
            pa = b.get("pa") or 0
            ops = b.get("ops")
            k_rate = b.get("k_rate")
            vals = dict(
                season=season,
                name=b["name"],
                team_short=b.get("team_short", ""),
                role="batter",
                pa=pa,
                ops=ops,
                k_rate=k_rate,
                db_game_count=0,
                source="statiz",
            )
            stmt = pg_insert(KboPlayerSeasonStat).values(**vals).on_conflict_do_update(
                constraint="uq_kbo_player_season",
                set_={"pa": pa, "ops": ops, "k_rate": k_rate, "source": "statiz"},
            )
            await db.execute(stmt)
            b_count += 1
    except Exception as e:
        logger.warning(f"statiz 타자 시드 스킵 (season={season}): {e}")

    await db.commit()
    logger.info(f"[player_stats] statiz 시드 완료: 투수 {p_count}명, 타자 {b_count}명 (season={season})")
    return {"pitchers": p_count, "batters": b_count}


async def ingest_final_game(db: AsyncSession, game: Game) -> bool:
    """종료된 KBO 경기 박스스코어 수집 + 시즌 스탯 재집계"""
    if game.league != "KBO" or game.status != "final" or not game.external_game_id:
        return False

    existing = (await db.execute(
        select(KboPlayerGameStat.id).where(KboPlayerGameStat.game_id == game.id).limit(1)
    )).scalar_one_or_none()
    if existing:
        return False

    box = await asyncio.to_thread(fetch_boxscore_sync, game.external_game_id)
    if not box:
        return False

    home_team = (await db.execute(select(Team).where(Team.id == game.home_team_id))).scalar_one_or_none()
    away_team = (await db.execute(select(Team).where(Team.id == game.away_team_id))).scalar_one_or_none()
    if not home_team or not away_team:
        return False

    season = game.game_date.year
    away_sp_hand = await _lookup_pitcher_handedness(db, box.get("away_starter"), away_team.short_name, season)
    home_sp_hand = await _lookup_pitcher_handedness(db, box.get("home_starter"), home_team.short_name, season)

    rows: list[dict] = []
    for b in box.get("home_batters") or []:
        if not b.get("name"):
            continue
        rows.append(_batter_game_row(game, season, home_team.short_name, b, away_sp_hand))
    for b in box.get("away_batters") or []:
        if not b.get("name"):
            continue
        rows.append(_batter_game_row(game, season, away_team.short_name, b, home_sp_hand))
    for p in box.get("home_pitchers") or []:
        if not p.get("name"):
            continue
        rows.append(_pitcher_game_row(game, season, home_team.short_name, p))
    for p in box.get("away_pitchers") or []:
        if not p.get("name"):
            continue
        rows.append(_pitcher_game_row(game, season, away_team.short_name, p))

    if not rows:
        return False

    for row in rows:
        stmt = pg_insert(KboPlayerGameStat).values(**row).on_conflict_do_update(
            constraint="uq_kbo_player_game",
            set_={k: row[k] for k in row if k not in ("game_id", "player_name", "role")},
        )
        await db.execute(stmt)

    affected = {r["player_name"] for r in rows}
    await recompute_season_stats(db, season, player_names=affected)
    await db.commit()
    logger.info(f"[player_stats] game_id={game.id} 박스스코어 {len(rows)}건 저장")
    return True


def _batter_game_row(game, season, team_short, b, opp_sp_throws) -> dict:
    return dict(
        game_id=game.id,
        season=season,
        game_date=game.game_date,
        player_name=b["name"],
        team_short=team_short,
        role="batter",
        is_starter=1 if b.get("order", 99) <= 9 else 0,
        opponent_sp_throws=opp_sp_throws,
        pa=b.get("pa", 0),
        ab=b.get("ab", 0),
        hits=b.get("hits", 0),
        doubles=b.get("doubles", 0),
        triples=b.get("triples", 0),
        hr=b.get("hr", 0),
        bb=b.get("bb", 0),
        so=b.get("so", 0),
        hbp=b.get("hbp", 0),
        sf=b.get("sf", 0),
        source="naver",
    )


def _pitcher_game_row(game, season, team_short, p) -> dict:
    return dict(
        game_id=game.id,
        season=season,
        game_date=game.game_date,
        player_name=p["name"],
        team_short=team_short,
        role="pitcher",
        is_starter=1 if p.get("is_starter") else 0,
        ip=p.get("ip", 0.0),
        er=p.get("er", 0),
        hits_allowed=p.get("hits_allowed", 0),
        bb_allowed=p.get("bb_allowed", 0),
        so_pitched=p.get("so_pitched", 0),
        source="naver",
    )


async def _lookup_pitcher_handedness(db, name, team_short, season) -> Optional[str]:
    if not name:
        return None
    from app.models.kbo_stats import KboPitcherStat

    for model, conds in (
        (KboPitcherStat, (
            KboPitcherStat.season == season,
            KboPitcherStat.name == name,
            KboPitcherStat.team_short == team_short,
            KboPitcherStat.handedness.isnot(None),
        )),
        (KboPlayerSeasonStat, (
            KboPlayerSeasonStat.season == season,
            KboPlayerSeasonStat.name == name,
            KboPlayerSeasonStat.team_short == team_short,
            KboPlayerSeasonStat.role == "pitcher",
            KboPlayerSeasonStat.handedness.isnot(None),
        )),
        (KboPlayerSeasonStat, (
            KboPlayerSeasonStat.season == season,
            KboPlayerSeasonStat.name == name,
            KboPlayerSeasonStat.role == "pitcher",
            KboPlayerSeasonStat.handedness.isnot(None),
        )),
    ):
        hand = (await db.execute(
            select(model.handedness).where(and_(*conds)).limit(1)
        )).scalar_one_or_none()
        if hand:
            return hand
    return None


async def recompute_season_stats(
    db: AsyncSession,
    season: int,
    player_names: Optional[set[str]] = None,
) -> None:
    """kbo_player_game_stats → kbo_player_season_stats 재집계"""
    q = select(KboPlayerGameStat).where(KboPlayerGameStat.season == season)
    game_rows = (await db.execute(q)).scalars().all()
    if player_names:
        game_rows = [r for r in game_rows if r.player_name in player_names]
    if not game_rows:
        return

    by_key: dict[tuple, list] = {}
    for r in game_rows:
        by_key.setdefault((r.player_name, r.team_short, r.role), []).append(r)

    for (name, team_short, role), lines in by_key.items():
        if role == "batter":
            await _upsert_batter_season(db, season, name, team_short, lines)
        else:
            await _upsert_pitcher_season(db, season, name, team_short, lines)


async def _upsert_batter_season(db, season, name, team_short, lines: list) -> None:
    pa = sum(l.pa for l in lines)
    ab = sum(l.ab for l in lines)
    hits = sum(l.hits for l in lines)
    doubles = sum(l.doubles for l in lines)
    triples = sum(l.triples for l in lines)
    hr = sum(l.hr for l in lines)
    bb = sum(l.bb for l in lines)
    so = sum(l.so for l in lines)
    hbp = sum(l.hbp for l in lines)
    sf = sum(l.sf for l in lines)
    ops = _calc_ops(ab, hits, doubles, triples, hr, bb, hbp, sf)
    k_rate = (so / pa) if pa > 0 else None
    db_count = len(lines)

    existing = (await db.execute(
        select(KboPlayerSeasonStat).where(
            and_(
                KboPlayerSeasonStat.season == season,
                KboPlayerSeasonStat.name == name,
                KboPlayerSeasonStat.team_short == team_short,
                KboPlayerSeasonStat.role == "batter",
            )
        )
    )).scalar_one_or_none()

    use_db = pa >= USE_DB_BATTER_MIN_PA
    source = "db" if use_db else (existing.source if existing else "statiz")

    vals = dict(
        season=season,
        name=name,
        team_short=team_short,
        role="batter",
        pa=pa,
        ab=ab,
        hits=hits,
        doubles=doubles,
        triples=triples,
        hr=hr,
        bb=bb,
        so=so,
        hbp=hbp,
        sf=sf,
        ops=ops if use_db else (existing.ops if existing else ops),
        k_rate=k_rate if use_db else (existing.k_rate if existing else k_rate),
        db_game_count=db_count,
        source=source,
    )
    if use_db:
        vals["ops"] = ops
        vals["k_rate"] = k_rate
        vals["source"] = "db"
    elif existing:
        vals["ops"] = existing.ops
        vals["k_rate"] = existing.k_rate

    stmt = pg_insert(KboPlayerSeasonStat).values(**vals).on_conflict_do_update(
        constraint="uq_kbo_player_season",
        set_={k: v for k, v in vals.items() if k not in ("season", "name", "team_short", "role")},
    )
    await db.execute(stmt)


async def _upsert_pitcher_season(db, season, name, team_short, lines: list) -> None:
    ip = sum(l.ip for l in lines)
    er = sum(l.er for l in lines)
    hits_allowed = sum(l.hits_allowed for l in lines)
    bb_allowed = sum(l.bb_allowed for l in lines)
    so_pitched = sum(l.so_pitched for l in lines)
    gs = sum(1 for l in lines if l.is_starter)
    games = len(lines)
    era, whip, k9 = _calc_pitching_rates(ip, er, hits_allowed, bb_allowed, so_pitched)

    ref_date = max(l.game_date for l in lines) + timedelta(days=1)
    recent_era, recent_whip = _recent_pitching_rates(lines, ref_date)

    existing = (await db.execute(
        select(KboPlayerSeasonStat).where(
            and_(
                KboPlayerSeasonStat.season == season,
                KboPlayerSeasonStat.name == name,
                KboPlayerSeasonStat.team_short == team_short,
                KboPlayerSeasonStat.role == "pitcher",
            )
        )
    )).scalar_one_or_none()

    use_db = ip >= USE_DB_PITCHER_MIN_IP
    handedness = existing.handedness if existing else None

    vals = dict(
        season=season,
        name=name,
        team_short=team_short,
        role="pitcher",
        ip=ip,
        er=er,
        hits_allowed=hits_allowed,
        bb_allowed=bb_allowed,
        so_pitched=so_pitched,
        gs=gs,
        games_pitched=games,
        handedness=handedness,
        db_game_count=games,
        source="db" if use_db else (existing.source if existing else "statiz"),
    )
    if use_db:
        vals.update(era=era, whip=whip, k9=k9, recent_era=recent_era, recent_whip=recent_whip, source="db")
    elif existing:
        vals.update(
            era=existing.era,
            whip=existing.whip,
            k9=existing.k9,
            recent_era=existing.recent_era,
            recent_whip=existing.recent_whip,
            ip=existing.ip,
        )

    stmt = pg_insert(KboPlayerSeasonStat).values(**vals).on_conflict_do_update(
        constraint="uq_kbo_player_season",
        set_={k: v for k, v in vals.items() if k not in ("season", "name", "team_short", "role")},
    )
    await db.execute(stmt)


async def get_db_pitcher_stats(
    db: AsyncSession,
    name: str,
    team_short: str,
    season: int,
) -> Optional[dict]:
    """자체 DB 시즌 스탯 (db 소스 우선, statiz 시드 폴백)"""
    import unicodedata
    names = [name, unicodedata.normalize("NFC", name)]
    for s in [season, season - 1]:
        for n in names:
            row = (await db.execute(
                select(KboPlayerSeasonStat).where(
                    and_(
                        KboPlayerSeasonStat.season == s,
                        KboPlayerSeasonStat.name == n,
                        KboPlayerSeasonStat.team_short == team_short,
                        KboPlayerSeasonStat.role == "pitcher",
                    )
                ).limit(1)
            )).scalars().first()
            if not row:
                row = (await db.execute(
                    select(KboPlayerSeasonStat).where(
                        and_(
                            KboPlayerSeasonStat.season == s,
                            KboPlayerSeasonStat.name == n,
                            KboPlayerSeasonStat.role == "pitcher",
                        )
                    ).limit(1)
                )).scalars().first()
            if not row:
                continue
            if row.source == "db" and row.ip >= USE_DB_PITCHER_MIN_IP:
                return {
                    "era": row.era,
                    "whip": row.whip,
                    "k9": row.k9,
                    "handedness": row.handedness,
                    "recent_era": row.recent_era,
                    "recent_whip": row.recent_whip,
                    "source": "db",
                }
            if row.source == "statiz" and row.era is not None:
                return {
                    "era": row.era,
                    "whip": row.whip,
                    "k9": row.k9,
                    "handedness": row.handedness,
                    "recent_era": row.recent_era,
                    "recent_whip": row.recent_whip,
                    "source": "statiz",
                }
    return None


async def get_db_pitcher_recent_stats(
    db: AsyncSession,
    name: str,
    team_short: str,
    season: int,
    before_date: date,
) -> tuple[Optional[float], Optional[float]]:
    """박스스코어 경기 로그 기준 최근 14일 ERA/WHIP (해당 경기일 이전만)"""
    import unicodedata
    names = [name, unicodedata.normalize("NFC", name)]
    for n in names:
        rows = (await db.execute(
            select(KboPlayerGameStat).where(
                and_(
                    KboPlayerGameStat.season == season,
                    KboPlayerGameStat.player_name == n,
                    KboPlayerGameStat.role == "pitcher",
                    KboPlayerGameStat.game_date < before_date,
                )
            )
        )).scalars().all()
        if rows:
            return _recent_pitching_rates(rows, before_date)
    return None, None


async def get_db_batter_ops(
    db: AsyncSession,
    name: str,
    team_short: str,
    season: int,
) -> Optional[float]:
    import unicodedata
    names = [name, unicodedata.normalize("NFC", name)]
    for s in [season, season - 1]:
        for n in names:
            row = (await db.execute(
                select(KboPlayerSeasonStat).where(
                    and_(
                        KboPlayerSeasonStat.season == s,
                        KboPlayerSeasonStat.name == n,
                        KboPlayerSeasonStat.team_short == team_short,
                        KboPlayerSeasonStat.role == "batter",
                    )
                ).limit(1)
            )).scalars().first()
            if not row:
                row = (await db.execute(
                    select(KboPlayerSeasonStat).where(
                        and_(
                            KboPlayerSeasonStat.season == s,
                            KboPlayerSeasonStat.name == n,
                            KboPlayerSeasonStat.role == "batter",
                        )
                    ).limit(1)
                )).scalars().first()
            if not row:
                continue
            if row.source == "db" and row.pa >= USE_DB_BATTER_MIN_PA and row.ops is not None:
                return row.ops
            if row.source == "statiz" and row.ops is not None:
                return row.ops
    return None


async def rebuild_team_stats_from_player_db(db: AsyncSession, season: int) -> dict:
    """Naver 박스스코어 누적 → 팀 타선/불펜 테이블 갱신 (statiz 불필요)"""
    from collections import defaultdict
    from app.models.kbo_stats import KboTeamBattingStat, KboTeamBullypenStat

    batters = (await db.execute(
        select(KboPlayerSeasonStat).where(
            and_(
                KboPlayerSeasonStat.season == season,
                KboPlayerSeasonStat.role == "batter",
                KboPlayerSeasonStat.pa > 0,
            )
        )
    )).scalars().all()

    team_pa: dict[str, int] = defaultdict(int)
    team_ops_w: dict[str, float] = defaultdict(float)
    team_k_w: dict[str, float] = defaultdict(float)
    for b in batters:
        if b.ops is None:
            continue
        team_pa[b.team_short] += b.pa
        team_ops_w[b.team_short] += b.ops * b.pa
        team_k_w[b.team_short] += (b.k_rate or 0.2) * b.pa

    batting_n = 0
    for team_short, pa in team_pa.items():
        if pa < 50:
            continue
        ops = round(team_ops_w[team_short] / pa, 3)
        k_rate = round(team_k_w[team_short] / pa, 3)
        wrc_plus = round(100 + (ops - 0.740) / 0.740 * 100, 1)
        vals = dict(season=season, team_short=team_short, ops=ops, wrc_plus=wrc_plus, k_rate=k_rate)
        stmt = pg_insert(KboTeamBattingStat).values(**vals).on_conflict_do_update(
            constraint="uq_kbo_team_batting",
            set_={"ops": ops, "wrc_plus": wrc_plus, "k_rate": k_rate},
        )
        await db.execute(stmt)
        batting_n += 1

    reliever_lines = (await db.execute(
        select(KboPlayerGameStat).where(
            and_(
                KboPlayerGameStat.season == season,
                KboPlayerGameStat.role == "pitcher",
                KboPlayerGameStat.is_starter == 0,
                KboPlayerGameStat.ip > 0,
            )
        )
    )).scalars().all()

    team_ip: dict[str, float] = defaultdict(float)
    team_era_w: dict[str, float] = defaultdict(float)
    team_whip_w: dict[str, float] = defaultdict(float)
    team_rel_count: dict[str, set] = defaultdict(set)
    for line in reliever_lines:
        if line.ip <= 0:
            continue
        era_g = line.er * 9.0 / line.ip
        whip_g = (line.hits_allowed + line.bb_allowed) / line.ip
        t = line.team_short
        team_ip[t] += line.ip
        team_era_w[t] += era_g * line.ip
        team_whip_w[t] += whip_g * line.ip
        team_rel_count[t].add(line.player_name)

    bullpen_n = 0
    for team_short, ip in team_ip.items():
        if ip < 10:
            continue
        bp_era = round(team_era_w[team_short] / ip, 2)
        bp_whip = round(team_whip_w[team_short] / ip, 3)
        cnt = len(team_rel_count[team_short])
        vals = dict(
            season=season, team_short=team_short,
            bullpen_era=bp_era, bullpen_whip=bp_whip, bullpen_count=cnt,
        )
        stmt = pg_insert(KboTeamBullypenStat).values(**vals).on_conflict_do_update(
            constraint="uq_kbo_team_bullpen",
            set_={"bullpen_era": bp_era, "bullpen_whip": bp_whip, "bullpen_count": cnt},
        )
        await db.execute(stmt)
        bullpen_n += 1

    await db.commit()
    logger.info(f"[player_stats] 팀 스탯 DB 집계 완료: 타선 {batting_n}팀, 불펜 {bullpen_n}팀 (season={season})")
    return {"team_batting": batting_n, "team_bullpen": bullpen_n}


async def backfill_from_final_games(db: AsyncSession, season: int) -> int:
    """시즌 내 종료 경기 박스스코어 일괄 수집 (초기 마이그레이션용)"""
    games = (await db.execute(
        select(Game).where(
            and_(
                Game.league == "KBO",
                Game.status == "final",
                Game.game_date >= date(season, 1, 1),
                Game.game_date < date(season + 1, 1, 1),
                Game.external_game_id.isnot(None),
            )
        ).order_by(Game.game_date.asc())
    )).scalars().all()

    count = 0
    for g in games:
        if await ingest_final_game(db, g):
            count += 1
    await rebuild_team_stats_from_player_db(db, season)
    return count
