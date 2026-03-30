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


async def run_for_date(target_date: date) -> None:
    """특정 날짜 미확정 경기 라인업 체크 및 업데이트"""
    logger.info(f"라인업 감시 시작 ({target_date})")

    async with AsyncSessionLocal() as db:
        # KBO 경기 중 라인업 미확정인 것만
        result = await db.execute(
            select(Game).where(
                Game.game_date == target_date,
                Game.league == "KBO",
                Game.status == "scheduled",
                Game.lineup_locked.is_(False) | Game.lineup_locked.is_(None),
            )
        )
        games = result.scalars().all()

        if not games:
            logger.info(f"라인업 확인 대상 경기 없음 ({target_date})")
            return

        logger.info(f"{len(games)}경기 라인업 확인 중... ({target_date})")

        from app.collectors.lineup_collector import KBOLineupCollector
        collector = KBOLineupCollector()

        updated_count = 0
        for game in games:
            if not game.external_game_id:
                logger.debug(f"game_id={game.id} external_game_id 없음 — 건너뜀")
                continue

            logger.debug(f"game_id={game.id} (external={game.external_game_id}) 라인업 요청 중...")
            try:
                lineup = await collector.fetch_lineup(game.external_game_id)
                if lineup:
                    logger.debug(
                        f"game_id={game.id} 라인업 응답: "
                        f"home_starter={lineup.get('home_starter')}, "
                        f"away_starter={lineup.get('away_starter')}, "
                        f"home_lineup={len(lineup.get('home_lineup') or [])}명, "
                        f"away_lineup={len(lineup.get('away_lineup') or [])}명"
                    )
                    changed = await _update_game_lineup(db, game, lineup)
                    if changed:
                        updated_count += 1
                        # 라인업 확정 시 예측 재실행
                        await _retrigger_prediction(db, game.id)
                else:
                    logger.info(f"game_id={game.id} 라인업 응답 없음 (아직 미발표)")
            except Exception as e:
                logger.warning(f"game_id={game.id} 라인업 수집 실패: {e}", exc_info=True)

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

    # 라인업 확정 (홈+원정 모두 있을 때)
    if home_lineup and away_lineup:
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
    """라인업 확정 시 예측 재실행"""
    try:
        from app.ml.predictor import Predictor
        from app.models import Game, Prediction
        from sqlalchemy import insert

        # 게임 리그 조회
        game_result = await db.execute(select(Game).where(Game.id == game_id))
        game = game_result.scalar_one_or_none()
        if not game:
            return

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
