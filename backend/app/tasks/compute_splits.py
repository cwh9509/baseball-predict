"""
팀 타선 좌/우완 스플릿 OPS 계산 (DB 기반)
statiz 스크래핑 없이, 기존 경기 결과 + 투수 handedness 데이터로 추정

방식:
  1. 완료된 KBO 경기에서 각 팀의 vs LHP / vs RHP 득점/경기 계산
  2. 팀 시즌 OPS 대비 득점 비율로 스플릿 OPS 추정
  3. kbo_team_batting_split_stats 테이블에 upsert
"""
import logging
from collections import defaultdict
from datetime import date

logger = logging.getLogger(__name__)

KBO_AVG_RUNS_PER_GAME = 4.8  # KBO 리그 평균 득점/경기


async def run(season: int) -> None:
    from sqlalchemy import select, and_, text
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.core.database import AsyncSessionLocal
    from app.models import Game, Team
    from app.models.kbo_stats import KboPitcherStat, KboTeamBattingStat, KboTeamBattingSplitStat

    async with AsyncSessionLocal() as db:
        # 1) 완료된 KBO 경기 조회 (최근 3시즌)
        games = (await db.execute(
            select(Game).where(
                and_(
                    Game.status == "final",
                    Game.league == "KBO",
                    Game.game_date >= date(season - 2, 1, 1),
                    Game.game_date < date(season + 1, 1, 1),
                )
            )
        )).scalars().all()

        if not games:
            logger.warning("[compute_splits] 완료된 KBO 경기 없음")
            return

        logger.info(f"[compute_splits] 대상 경기: {len(games)}경기 (최근 3시즌)")

        # 2) 투수 handedness 조회 (자체 DB → statiz 폴백)
        hand_map: dict[str, str] = {}
        from app.models.kbo_player_stats import KboPlayerSeasonStat
        ps_rows = (await db.execute(
            select(KboPlayerSeasonStat).where(
                KboPlayerSeasonStat.role == "pitcher",
                KboPlayerSeasonStat.handedness.isnot(None),
            )
        )).scalars().all()
        for p in ps_rows:
            if p.name not in hand_map:
                hand_map[p.name] = p.handedness
        pitcher_rows = (await db.execute(
            select(KboPitcherStat).where(KboPitcherStat.handedness.isnot(None))
        )).scalars().all()
        for p in pitcher_rows:
            if p.name not in hand_map:
                hand_map[p.name] = p.handedness

        # 3) 팀 ID → short_name 매핑
        teams = (await db.execute(select(Team).where(Team.league == "KBO"))).scalars().all()
        team_short: dict[int, str] = {t.id: t.short_name for t in teams}

        # 4) 팀별 vs LHP / vs RHP 득점 집계
        # {team_short: {"lhp_runs": [], "rhp_runs": []}}
        team_stats: dict[str, dict] = defaultdict(lambda: {"lhp_runs": [], "rhp_runs": []})

        for g in games:
            home_short = team_short.get(g.home_team_id)
            away_short = team_short.get(g.away_team_id)
            if not home_short or not away_short:
                continue

            home_runs = g.home_score or 0
            away_runs = g.away_score or 0
            home_sp_hand = hand_map.get(g.home_starter_name or "")
            away_sp_hand = hand_map.get(g.away_starter_name or "")

            # away팀 타선은 home 선발(away_sp_hand... 아래 주의: away_sp = 원정 선발 → home 팀 상대)
            # home팀이 상대하는 선발 = away 선발
            if away_sp_hand:
                if away_sp_hand == "L":
                    team_stats[home_short]["lhp_runs"].append(home_runs)
                else:
                    team_stats[home_short]["rhp_runs"].append(home_runs)

            if home_sp_hand:
                if home_sp_hand == "L":
                    team_stats[away_short]["lhp_runs"].append(away_runs)
                else:
                    team_stats[away_short]["rhp_runs"].append(away_runs)

        # 5) 팀 시즌 OPS 조회 (비율 계산 기준)
        team_ops: dict[str, float] = {}
        for s in [season, season - 1]:
            rows = (await db.execute(select(KboTeamBattingStat).where(KboTeamBattingStat.season == s))).scalars().all()
            for r in rows:
                if r.team_short not in team_ops:
                    team_ops[r.team_short] = r.ops

        # 6) 스플릿 OPS 계산 및 upsert
        upserted = 0
        for short, stats in team_stats.items():
            base_ops = team_ops.get(short, 0.740)
            lhp_list = stats["lhp_runs"]
            rhp_list = stats["rhp_runs"]

            if len(lhp_list) >= 5:
                lhp_avg = sum(lhp_list) / len(lhp_list)
                lhp_ratio = lhp_avg / KBO_AVG_RUNS_PER_GAME
                lhp_ops = round(base_ops * lhp_ratio, 3)
                stmt = pg_insert(KboTeamBattingSplitStat).values(
                    season=season, team_short=short, split="vs_lhp",
                    ops=lhp_ops, pa=len(lhp_list),
                ).on_conflict_do_update(
                    constraint="uq_kbo_team_batting_split",
                    set_={"ops": lhp_ops, "pa": len(lhp_list)},
                )
                await db.execute(stmt)
                upserted += 1
                logger.debug(f"  {short} vs LHP: avg={lhp_avg:.2f}득점 ({len(lhp_list)}경기) → OPS={lhp_ops}")

            if len(rhp_list) >= 5:
                rhp_avg = sum(rhp_list) / len(rhp_list)
                rhp_ratio = rhp_avg / KBO_AVG_RUNS_PER_GAME
                rhp_ops = round(base_ops * rhp_ratio, 3)
                stmt = pg_insert(KboTeamBattingSplitStat).values(
                    season=season, team_short=short, split="vs_rhp",
                    ops=rhp_ops, pa=len(rhp_list),
                ).on_conflict_do_update(
                    constraint="uq_kbo_team_batting_split",
                    set_={"ops": rhp_ops, "pa": len(rhp_list)},
                )
                await db.execute(stmt)
                upserted += 1
                logger.debug(f"  {short} vs RHP: avg={rhp_avg:.2f}득점 ({len(rhp_list)}경기) → OPS={rhp_ops}")

        await db.commit()
        logger.info(f"[compute_splits] 완료: {upserted}개 스플릿 저장, handedness 매핑 {len(hand_map)}명")
