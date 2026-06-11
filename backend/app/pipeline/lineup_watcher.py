"""
라인업 감시기
경기 당일 12:00 ~ 19:30 (KST) 30분 간격으로 실행
  - 주말(토·일): 14:00 시작 → 라인업 12:00~13:30 발표
  - 평일(월~금): 18:30 시작 → 라인업 16:30~17:30 발표
라인업 발표 감지 → DB 업데이트 → 예측 재실행

scheduler.py에서 호출:
  from app.pipeline.lineup_watcher import run as run_lineup_watch
"""
import asyncio
import logging
from datetime import date, datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import Game

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


def _in_kbo_lineup_peak(now_kst: datetime) -> bool:
    """KBO 라인업 발표 집중 감시 시간대 (KST)
    평일: 16:30~18:30 (17:00 전후 발표)
    주말: 12:00~14:00 (14:00 경기 전후 발표)
    """
    minutes = now_kst.hour * 60 + now_kst.minute
    if now_kst.weekday() < 5:
        return 16 * 60 + 30 <= minutes <= 18 * 60 + 30
    return 12 * 60 <= minutes <= 14 * 60


def _lineup_batter_count(lineup_json) -> int:
    if not lineup_json or not isinstance(lineup_json, list):
        return 0
    return len(lineup_json)


def _needs_lineup_refresh(game: Game) -> bool:
    """선발만 있거나 타순이 9명 미만이면 계속 수집"""
    home_n = _lineup_batter_count(game.home_lineup_json)
    away_n = _lineup_batter_count(game.away_lineup_json)
    if home_n < 9 or away_n < 9:
        return True
    if not game.home_starter_name or not game.away_starter_name:
        return True
    return False


async def run_kbo_peak() -> None:
    """17:00 KST 전후 라인업 발표 집중 감시 (스케줄러 10분 간격 호출)"""
    now_kst = datetime.now(KST)
    if not _in_kbo_lineup_peak(now_kst):
        return
    logger.info(f"KBO 라인업 집중 감시 ({now_kst.strftime('%H:%M')} KST)")
    await run_for_date(now_kst.date())


async def run() -> None:
    """당일 미확정 KBO 경기 라인업 체크 및 업데이트"""
    today = datetime.now(KST).date()
    await run_for_date(today)


async def run_mlb() -> None:
    """당일 미확정 MLB 경기 선발투수 체크 및 업데이트"""
    # MLB 경기는 미국 동부 날짜 기준으로 저장됨 — ET 날짜 사용
    from dateutil import tz as dateutil_tz
    ET = dateutil_tz.gettz("America/New_York")
    today_et = datetime.now(ET).date()
    await run_for_date_mlb(today_et)


async def run_for_date_mlb(target_date: date) -> None:
    """MLB probable pitchers + statsapi boxscore 라인업 수집 및 예측 재실행"""
    logger.info(f"MLB 라인업 감시 시작 ({target_date})")

    import httpx
    from app.models import Team

    # statsapi 스케줄에서 probable pitchers + 팀 약어 조회
    # (game_pk → (home_abbr, away_abbr, home_starter, away_starter))
    pk_info: dict[str, tuple[str, str, Optional[str], Optional[str]]] = {}
    # (home_abbr, away_abbr) → game_pk
    team_to_pk: dict[tuple[str, str], str] = {}

    try:
        def _fetch_schedule():
            return httpx.get(
                "https://statsapi.mlb.com/api/v1/schedule",
                params={"sportId": 1, "date": target_date.isoformat(), "hydrate": "probablePitcher"},
                timeout=15,
            ).json()

        sched = await asyncio.to_thread(_fetch_schedule)
        for d in sched.get("dates", []):
            for g in d.get("games", []):
                gid = str(g.get("gamePk", ""))
                home_abbr = g["teams"]["home"]["team"].get("abbreviation", "")
                away_abbr = g["teams"]["away"]["team"].get("abbreviation", "")
                home_sp = g["teams"]["home"].get("probablePitcher", {}).get("fullName") or None
                away_sp = g["teams"]["away"].get("probablePitcher", {}).get("fullName") or None
                if gid and home_abbr and away_abbr:
                    pk_info[gid] = (home_abbr, away_abbr, home_sp, away_sp)
                    team_to_pk[(home_abbr, away_abbr)] = gid
    except Exception as e:
        logger.warning(f"statsapi 스케줄 조회 실패 ({target_date}): {e}")

    from app.collectors.mlb_lineup_collector import fetch_mlb_lineup

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Game).where(
                Game.game_date == target_date,
                Game.league == "MLB",
                Game.status == "scheduled",
            )
        )
        games = [g for g in result.scalars().all() if _needs_lineup_refresh(g)]

        if not games:
            logger.info(f"MLB 라인업 확인 대상 경기 없음 ({target_date})")
            return

        logger.info(f"MLB {len(games)}경기 라인업 확인 중... ({target_date})")

        updated_count = 0
        for game in games:
            try:
                game_pk = game.external_game_id

                # external_game_id 없으면 팀 약어로 statsapi gamePk 찾기
                if not game_pk:
                    home_team = (await db.execute(select(Team).where(Team.id == game.home_team_id))).scalar_one_or_none()
                    away_team = (await db.execute(select(Team).where(Team.id == game.away_team_id))).scalar_one_or_none()
                    if home_team and away_team:
                        game_pk = team_to_pk.get((home_team.short_name, away_team.short_name))
                        if game_pk:
                            # DB에 external_game_id 저장
                            await db.execute(
                                update(Game).where(Game.id == game.id).values(external_game_id=game_pk)
                            )
                            await db.commit()
                            logger.info(f"MLB game_id={game.id} external_game_id 복구: {game_pk}")

                if not game_pk:
                    logger.debug(f"MLB game_id={game.id} statsapi gamePk 찾기 실패 — 스킵")
                    continue

                # probable pitchers
                info = pk_info.get(game_pk)
                home_starter = info[2] if info else None
                away_starter = info[3] if info else None

                lineup_data = None
                if home_starter or away_starter:
                    lineup_data = {
                        "home_starter": home_starter,
                        "away_starter": away_starter,
                        "home_lineup": [],
                        "away_lineup": [],
                        "confirmed": bool(home_starter and away_starter),
                        "source": "mlb_schedule",
                    }

                # statsapi live feed로 타순 보완 (라인업 발표 후 ~ 경기 중)
                boxscore = await fetch_mlb_lineup(game_pk)
                if boxscore:
                    if lineup_data:
                        lineup_data["home_starter"] = lineup_data.get("home_starter") or boxscore.get("home_starter")
                        lineup_data["away_starter"] = lineup_data.get("away_starter") or boxscore.get("away_starter")
                        if boxscore.get("home_lineup"):
                            lineup_data["home_lineup"] = boxscore["home_lineup"]
                        if boxscore.get("away_lineup"):
                            lineup_data["away_lineup"] = boxscore["away_lineup"]
                    else:
                        lineup_data = boxscore

                if lineup_data:
                    changed = await _update_game_lineup(db, game, lineup_data)
                    if changed:
                        updated_count += 1
                        await _retrigger_prediction(db, game.id)

            except Exception as e:
                logger.warning(f"MLB game_id={game.id} 라인업 수집 실패: {e}")

    logger.info(f"MLB 라인업 감시 완료 — {updated_count}경기 업데이트 ({target_date})")


async def _fetch_naver_mlb_game_ids(target_date: date) -> dict:
    """Naver MLB 일정에서 {statsapi_game_pk: naver_game_id} 매핑 반환"""
    import httpx

    date_str = target_date.strftime("%Y%m%d")
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
        "Referer": "https://m.sports.naver.com/",
        "Accept": "application/json",
    }

    def _fetch():
        try:
            resp = httpx.get(
                "https://api-gw.sports.naver.com/schedule/games",
                params={"gameDate": date_str, "categoryId": "mlb"},
                headers=headers,
                timeout=10,
            )
            if resp.status_code != 200:
                return {}
            games = resp.json().get("result", {}).get("games", [])
            # Naver MLB gameId 예: 20260408ATAN0
            # statsapi와 매핑하기 위해 홈팀/원정팀 코드로 매칭
            result = {}
            for g in games:
                naver_id = g.get("gameId", "")
                if naver_id:
                    result[naver_id] = naver_id  # 일단 naver_id 자체를 저장
            return result
        except Exception as e:
            logger.debug(f"Naver MLB 일정 수집 실패: {e}")
            return {}

    naver_games = await asyncio.to_thread(_fetch)

    # statsapi 일정과 Naver 일정을 팀명으로 매핑
    # Naver MLB 팀코드 → statsapi 팀 약어 매핑
    NAVER_MLB_CODE: dict = {
        "AT": "ATL", "AN": "LAA", "BA": "BAL", "BO": "BOS", "CH": "CHC",
        "CW": "CWS", "CI": "CIN", "CL": "CLE", "CO": "COL", "DE": "DET",
        "HO": "HOU", "KC": "KC", "LA": "LAD", "MI": "MIA", "MN": "MIN",
        "ML": "MIL", "NY": "NYM", "YA": "NYY", "OK": "OAK", "PH": "PHI",
        "PI": "PIT", "SD": "SD", "SF": "SF", "SE": "SEA", "SL": "STL",
        "TB": "TB", "TE": "TEX", "TO": "TOR", "WA": "WSH",
    }

    # game_pk → naver_game_id 매핑을 위해 statsapi 일정도 조회
    from app.collectors.mlb_lineup_collector import fetch_mlb_schedule_starters
    # 이미 starters_map에서 game_pk 목록을 알고 있으므로
    # Naver game ID에서 홈팀 코드 추출 → short_name 변환 → DB에서 매핑
    pk_to_naver = {}
    for naver_id in naver_games:
        if len(naver_id) >= 12:
            away_code = naver_id[8:10]
            home_code = naver_id[10:12]
            home_short = NAVER_MLB_CODE.get(home_code)
            away_short = NAVER_MLB_CODE.get(away_code)
            if home_short and away_short:
                # DB에서 home/away팀으로 game_pk 찾기
                async with AsyncSessionLocal() as db:
                    from app.models import Team
                    from sqlalchemy import select
                    home_team = (await db.execute(
                        select(Game).where(
                            Game.game_date == target_date,
                            Game.league == "MLB",
                        )
                    )).scalars().all()
                    for g in home_team:
                        home_t = (await db.execute(
                            select(Team).where(Team.id == g.home_team_id)
                        )).scalar_one_or_none()
                        away_t = (await db.execute(
                            select(Team).where(Team.id == g.away_team_id)
                        )).scalar_one_or_none()
                        if (home_t and away_t and
                            home_t.short_name == home_short and
                            away_t.short_name == away_short):
                            pk_to_naver[g.external_game_id] = naver_id
                            break

    return pk_to_naver


async def run_pre_game() -> None:
    """경기 시작 30분 전 이내인 미확정 경기만 집중 감시 (10분 간격 호출용)"""
    now_kst = datetime.now(KST)
    today = now_kst.date()

    logger.info(f"경기 시작 전 집중 감시 시작 ({now_kst.strftime('%H:%M')})")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Game).where(
                Game.game_date == today,
                Game.league == "KBO",
                Game.status == "scheduled",
                (Game.lineup_locked.is_(False) | Game.lineup_locked.is_(None) |
                 Game.home_lineup_json.is_(None) | Game.away_lineup_json.is_(None)),
                Game.game_time.isnot(None),
            )
        )
        games = result.scalars().all()

        # 시작 60분 전 이내 경기만 필터 (라인업은 60분 전에 발표됨)
        target_games = []
        for game in games:
            try:
                h, m, *_ = str(game.game_time).split(":")
                game_dt = now_kst.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
                minutes_until = (game_dt - now_kst).total_seconds() / 60
                if 0 <= minutes_until <= 60:
                    target_games.append(game)
            except Exception:
                continue

        if not target_games:
            logger.info("30분 내 시작 예정 미확정 경기 없음")
            return

        logger.info(f"{len(target_games)}경기 집중 감시 중...")

        from app.collectors.naver_lineup_collector import NaverLineupCollector
        from app.collectors.lineup_collector import KBOLineupCollector
        naver_collector = NaverLineupCollector()
        kbo_collector = KBOLineupCollector()

        for game in target_games:
            if not game.external_game_id:
                continue
            try:
                lineup = await naver_collector.fetch_lineup(game.external_game_id)
                if not lineup:
                    lineup = await kbo_collector.fetch_lineup(game.external_game_id)
                if lineup:
                    changed = await _update_game_lineup(db, game, lineup)
                    if changed:
                        await _retrigger_prediction(db, game.id)
                    else:
                        logger.info(f"game_id={game.id} 라인업 변경 없음")
                else:
                    logger.info(f"game_id={game.id} 아직 라인업 미발표")
            except Exception as e:
                logger.warning(f"game_id={game.id} 집중 감시 실패: {e}")


async def run_for_date(target_date: date) -> None:
    """특정 날짜 미확정 경기 라인업 체크 및 업데이트
    KBO 일정 API에서 선발투수 확인 → 양쪽 확정 시 lineup_locked=True
    """
    logger.info(f"라인업 감시 시작 ({target_date})")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Game).where(
                Game.game_date == target_date,
                Game.league == "KBO",
                Game.status == "scheduled",
            )
        )
        games = [g for g in result.scalars().all() if _needs_lineup_refresh(g)]

        if not games:
            logger.info(f"라인업 확인 대상 경기 없음 ({target_date})")
            return

        logger.info(f"{len(games)}경기 라인업 확인 중... ({target_date})")

        # KBO 일정 API에서 선발투수 최신 정보 가져오기
        from app.collectors.kbo_collector import KBOCollector
        kbo_collector = KBOCollector()
        try:
            schedule_games = await kbo_collector.fetch_schedule(target_date)
        except Exception as e:
            logger.warning(f"KBO 일정 수집 실패: {e}")
            schedule_games = []

        # external_game_id → (home_starter, away_starter) 매핑
        starter_map: dict[str, tuple[Optional[str], Optional[str]]] = {}
        for raw in schedule_games:
            if raw.external_game_id:
                starter_map[raw.external_game_id] = (raw.home_starter_name, raw.away_starter_name)

        from app.collectors.naver_lineup_collector import NaverLineupCollector
        from app.collectors.lineup_collector import KBOLineupCollector
        naver_collector = NaverLineupCollector()
        kbo_collector_lc = KBOLineupCollector()

        now_kst = datetime.now(KST)

        updated_count = 0
        for game in games:
            # 이미 시작된 경기는 예측 불필요 — 스킵
            if game.game_time:
                try:
                    h, m, *_ = str(game.game_time).split(":")
                    game_dt = now_kst.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
                    if now_kst >= game_dt:
                        logger.debug(f"game_id={game.id} 이미 시작된 경기 — 라인업 감시 스킵")
                        continue
                except Exception:
                    pass

            starters = starter_map.get(game.external_game_id or "")
            home_starter = starters[0] if starters else None
            away_starter = starters[1] if starters else None

            # 스케줄 API에서 선발 없으면 Naver 우선, KBO 폴백
            lineup_source = "schedule" if (home_starter and away_starter) else None
            home_lineup: list = []
            away_lineup: list = []

            need_fetch = (
                not home_starter or not away_starter
                or len(home_lineup) < 9 or len(away_lineup) < 9
            )
            if game.external_game_id and need_fetch:
                try:
                    lc_result = await naver_collector.fetch_lineup(game.external_game_id)
                    if lc_result:
                        home_starter = home_starter or lc_result.get("home_starter")
                        away_starter = away_starter or lc_result.get("away_starter")
                        if len(home_lineup) < 9:
                            home_lineup = lc_result.get("home_lineup") or home_lineup
                        if len(away_lineup) < 9:
                            away_lineup = lc_result.get("away_lineup") or away_lineup
                        lineup_source = lc_result.get("source")
                        logger.info(f"game_id={game.id} Naver 선발: home={home_starter}, away={away_starter} ({lineup_source}) 타순: home={len(home_lineup)}명, away={len(away_lineup)}명")
                except Exception as e:
                    logger.debug(f"game_id={game.id} Naver collector 실패: {e}")

            # Naver도 없으면 KBO lineup collector 폴백
            if game.external_game_id and need_fetch:
                try:
                    lc_result = await kbo_collector_lc.fetch_lineup(game.external_game_id)
                    if lc_result:
                        home_starter = home_starter or lc_result.get("home_starter")
                        away_starter = away_starter or lc_result.get("away_starter")
                        if not home_lineup:
                            home_lineup = lc_result.get("home_lineup") or []
                        if not away_lineup:
                            away_lineup = lc_result.get("away_lineup") or []
                        lineup_source = lc_result.get("source")
                except Exception as e:
                    logger.debug(f"game_id={game.id} KBO lineup collector 폴백 실패: {e}")

            # naver_preview는 양쪽 선발 모두 있을 때만 확정, 나머지 소스는 무조건 확정
            is_confirmed = lineup_source not in ("naver_preview", None) or (bool(home_starter) and bool(away_starter))
            lineup = {
                "home_starter": home_starter,
                "away_starter": away_starter,
                "home_lineup": home_lineup,
                "away_lineup": away_lineup,
                "confirmed": is_confirmed,
            }
            changed = await _update_game_lineup(db, game, lineup)
            if changed:
                updated_count += 1
                await _retrigger_prediction(db, game.id)
            else:
                logger.debug(f"game_id={game.id} 선발투수 미확정 (home={game.home_starter_name}, away={game.away_starter_name})")

    logger.info(f"라인업 감시 완료 — {updated_count}경기 업데이트 ({target_date})")


async def _update_game_lineup(db: AsyncSession, game: Game, lineup: dict) -> bool:
    """게임 라인업 DB 업데이트. 변경 있으면 True 반환"""
    now = datetime.now(timezone.utc)
    changed = False

    updates: dict = {}

    # 선발투수 확인 (현재 없거나 다를 때만 업데이트)
    home_starter = lineup.get("home_starter")
    away_starter = lineup.get("away_starter")

    if home_starter and game.home_starter_name != home_starter:
        updates["home_starter_name"] = home_starter
        logger.info(f"[game {game.id}] 홈 선발 확정: {home_starter}")
        changed = True

    if away_starter and game.away_starter_name != away_starter:
        updates["away_starter_name"] = away_starter
        logger.info(f"[game {game.id}] 원정 선발 확정: {away_starter}")
        changed = True

    # 타순 저장
    home_lineup = lineup.get("home_lineup") or []
    away_lineup = lineup.get("away_lineup") or []

    if home_lineup and game.home_lineup_json != home_lineup:
        updates["home_lineup_json"] = home_lineup
        changed = True

    if away_lineup and game.away_lineup_json != away_lineup:
        updates["away_lineup_json"] = away_lineup
        changed = True

    # 라인업 확정 — 실제 타순(9명)이 양쪽 모두 있을 때만 locked
    # 선발투수만 있는 경우(preview)는 locked 안 함 → 경기 시작 후 타순 수집 계속
    confirmed = lineup.get("confirmed", True)
    final_home_starter = home_starter or game.home_starter_name
    final_away_starter = away_starter or game.away_starter_name
    has_full_batting_order = len(home_lineup) >= 9 and len(away_lineup) >= 9
    if confirmed and final_home_starter and final_away_starter and has_full_batting_order:
        if not game.lineup_locked:
            updates["lineup_locked"] = True
            updates["lineup_locked_at"] = now
            changed = True
    elif game.lineup_locked and not has_full_batting_order:
        # 선발만 있을 때 잘못 locked 된 경우 해제
        updates["lineup_locked"] = False
        updates["lineup_locked_at"] = None
        changed = True

    if updates:
        updates["updated_at"] = now
        await db.execute(
            update(Game).where(Game.id == game.id).values(**updates)
        )
        await db.commit()

    return changed


async def _retrigger_prediction(db: AsyncSession, game_id: int) -> None:
    """라인업 확정 시 날씨 갱신 후 예측 재실행"""
    try:
        from app.ml.predictor import Predictor
        from app.models import Game, Prediction
        from sqlalchemy import insert

        # 게임 리그 조회
        game_result = await db.execute(select(Game).where(Game.id == game_id))
        game = game_result.scalar_one_or_none()
        if not game:
            return

        # 날씨 강제 갱신 (라인업 확정 시점의 최신 날씨 반영)
        try:
            from app.pipeline.etl_runner import ETLRunner
            etl = ETLRunner()
            await etl.refresh_weather_for_game(db, game)
        except Exception as e:
            logger.warning(f"game_id={game_id} 날씨 갱신 실패 (예측은 계속): {e}")

        predictor = Predictor(league=game.league)
        result = await predictor.predict(game_id, db)
        if not result:
            return

        # 기존 예측이 있으면 덮어쓰기, 없으면 새로 삽입
        existing = await db.execute(
            select(Prediction).where(Prediction.game_id == game_id)
            .order_by(Prediction.predicted_at.desc()).limit(1)
        )
        pred = existing.scalar_one_or_none()

        if pred:
            await db.execute(
                update(Prediction).where(Prediction.id == pred.id).values(
                    model_version=result["model_version"],
                    predicted_winner_id=result["predicted_winner_id"],
                    home_win_prob=result["home_win_prob"],
                    confidence_tier=result["confidence_tier"],
                    feature_snapshot=result["feature_snapshot"],
                    predicted_home_score=result.get("predicted_home_score"),
                    predicted_away_score=result.get("predicted_away_score"),
                    predicted_at=datetime.now(timezone.utc),
                    llm_explanation=None,   # 라인업 변경 시 설명 초기화
                    llm_generated_at=None,
                )
            )
        else:
            await db.execute(
                insert(Prediction).values(
                    game_id=game_id,
                    model_version=result["model_version"],
                    predicted_winner_id=result["predicted_winner_id"],
                    home_win_prob=result["home_win_prob"],
                    confidence_tier=result["confidence_tier"],
                    feature_snapshot=result["feature_snapshot"],
                )
            )
        await db.commit()
        logger.info(f"game_id={game_id} 라인업 기반 예측 재실행 완료 (홈 승률: {result['home_win_prob']:.1%})")

        # 캐시 무효화 (라인업 반영된 예측이 즉시 서빙되도록)
        try:
            from app.core.redis_client import cache_delete
            cache_key = f"games:today:{game.league}:{game.game_date.isoformat()}"
            await cache_delete(cache_key)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"game_id={game_id} 예측 재실행 실패: {e}")
