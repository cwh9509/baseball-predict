"""
라인업 감시기
경기 당일 12:00 ~ 19:30 (KST) 30분 간격으로 실행
  - 주말(토·일): 14:00 시작 → 라인업 12:00~13:30 발표
  - 평일(월~금): 18:30 시작 → 라인업 16:30~17:30 발표
라인업 발표 감지 → DB 업데이트 → 예측 재실행

scheduler.py에서 호출:
  from app.pipeline.lineup_watcher import run as run_lineup_watch
"""
import logging
from datetime import date, datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import Game

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


async def run() -> None:
    """당일 미확정 경기 라인업 체크 및 업데이트"""
    today = datetime.now(KST).date()
    await run_for_date(today)


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
                Game.lineup_locked.is_(False) | Game.lineup_locked.is_(None),
                Game.game_time.isnot(None),
            )
        )
        games = result.scalars().all()

        # 시작 30분 전 이내 경기만 필터
        target_games = []
        for game in games:
            try:
                h, m, *_ = str(game.game_time).split(":")
                game_dt = now_kst.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
                minutes_until = (game_dt - now_kst).total_seconds() / 60
                if 0 <= minutes_until <= 30:
                    target_games.append(game)
            except Exception:
                continue

        if not target_games:
            logger.info("30분 내 시작 예정 미확정 경기 없음")
            return

        logger.info(f"{len(target_games)}경기 집중 감시 중...")

        from app.collectors.lineup_collector import KBOLineupCollector
        collector = KBOLineupCollector()

        for game in target_games:
            if not game.external_game_id:
                continue
            try:
                lineup = await collector.fetch_lineup(game.external_game_id)
                if lineup:
                    changed = await _update_game_lineup(db, game, lineup)
                    if changed:
                        await _retrigger_prediction(db, game.id)
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
                # 선발투수 미확정이면 lineup_locked여도 재수집
                (Game.lineup_locked.is_(False) | Game.lineup_locked.is_(None) |
                 Game.home_starter_name.is_(None) | Game.away_starter_name.is_(None)),
            )
        )
        games = result.scalars().all()

        if not games:
            logger.info(f"라인업 확인 대상 경기 없음 ({target_date})")
            return

        logger.info(f"{len(games)}경기 선발투수 확인 중... ({target_date})")

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

        updated_count = 0
        for game in games:
            starters = starter_map.get(game.external_game_id or "")
            home_starter = starters[0] if starters else None
            away_starter = starters[1] if starters else None

            # 스케줄 API에서 선발 없으면 Naver 우선, KBO 폴백
            if (not home_starter or not away_starter) and game.external_game_id:
                try:
                    lc_result = await naver_collector.fetch_lineup(game.external_game_id)
                    if lc_result:
                        home_starter = home_starter or lc_result.get("home_starter")
                        away_starter = away_starter or lc_result.get("away_starter")
                        logger.info(f"game_id={game.id} Naver 선발: home={home_starter}, away={away_starter} ({lc_result.get('source')})")
                except Exception as e:
                    logger.debug(f"game_id={game.id} Naver collector 실패: {e}")

            # Naver도 없으면 KBO lineup collector 폴백
            if (not home_starter or not away_starter) and game.external_game_id:
                try:
                    lc_result = await kbo_collector_lc.fetch_lineup(game.external_game_id)
                    if lc_result:
                        home_starter = home_starter or lc_result.get("home_starter")
                        away_starter = away_starter or lc_result.get("away_starter")
                except Exception as e:
                    logger.debug(f"game_id={game.id} KBO lineup collector 폴백 실패: {e}")

            lineup = {
                "home_starter": home_starter,
                "away_starter": away_starter,
                "home_lineup": [],
                "away_lineup": [],
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

    # 라인업 확정 — 양쪽 선발투수 확정되면 locked (타순은 부가 정보)
    final_home_starter = home_starter or game.home_starter_name
    final_away_starter = away_starter or game.away_starter_name
    if final_home_starter and final_away_starter and not game.lineup_locked:
        updates["lineup_locked"] = True
        updates["lineup_locked_at"] = now

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

    except Exception as e:
        logger.error(f"game_id={game_id} 예측 재실행 실패: {e}")
