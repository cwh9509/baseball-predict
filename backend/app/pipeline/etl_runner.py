"""
ETL 파이프라인 오케스트레이터
수집 → 정제 → DB 저장까지의 전체 흐름 관리

멱등성 보장: ON CONFLICT DO UPDATE 사용 (중복 실행 안전)
사용 예시:
  python -m app.pipeline.etl_runner --date 2024-04-15
  python -m app.pipeline.etl_runner --backfill --from 2023-04-01 --to 2023-10-01
"""
import argparse
import asyncio
import logging
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.base_collector import GameRaw
from app.collectors.pybaseball_collector import PybaseballCollector, MLB_TEAMS
from app.collectors.kbo_collector import KBOCollector, KBO_TEAMS
from app.collectors.npb_collector import NPBCollector, NPB_TEAMS
from app.collectors.weather_collector import WeatherCollector
from app.core.database import AsyncSessionLocal
from app.config import settings
from app.models import Game, Player, Team, WeatherLog
from app.pipeline.normalizer import normalize_game, normalize_team

logger = logging.getLogger(__name__)


def _get_team_coords(league: str, short_name: str) -> Optional[dict]:
    if league == "KBO":
        info = KBO_TEAMS.get(short_name)
    elif league == "NPB":
        info = NPB_TEAMS.get(short_name)
    else:
        info = MLB_TEAMS.get(short_name)
    if info:
        return {"lat": info["lat"], "lon": info["lon"]}
    return None


class ETLRunner:

    def __init__(self, league: Optional[str] = None, skip_weather: bool = False):
        self.league = (league or settings.league).upper()
        if self.league == "KBO":
            self.collector = KBOCollector()
        elif self.league == "NPB":
            self.collector = NPBCollector()
        elif self.league == "MLB":
            self.collector = PybaseballCollector()
        else:
            self.collector = PybaseballCollector()
        self.weather = WeatherCollector()
        self.skip_weather = skip_weather

    async def run_for_date(self, target_date: date) -> None:
        """특정 날짜의 전체 ETL 실행"""
        logger.info(f"ETL 시작: {target_date}")
        async with AsyncSessionLocal() as db:
            # 1. 팀 데이터 초기화 (최초 실행 시)
            await self._ensure_teams(db)

            # 2. 경기 일정/결과 수집 → upsert (statiz 실패 시 Naver 폴백)
            games_raw = await self.collector.fetch_schedule(target_date)
            if not games_raw:
                logger.warning(f"{target_date}: statiz 일정 수집 실패, Naver 폴백 시도")
                from app.collectors.naver_lineup_collector import NaverLineupCollector
                from app.collectors.base_collector import GameRaw
                naver = NaverLineupCollector()
                naver_games = await naver.fetch_schedule(target_date)
                if naver_games:
                    games_raw = [
                        GameRaw(
                            league="KBO",
                            game_date=g["game_date"],
                            home_team_short=g["home_team_short"],
                            away_team_short=g["away_team_short"],
                            status=g["status"],
                            home_score=g.get("home_score"),
                            away_score=g.get("away_score"),
                            external_game_id=g.get("external_game_id"),
                            venue=g.get("venue", ""),
                            game_time_local=g.get("game_time"),
                        )
                        for g in naver_games
                    ]
                    logger.info(f"{target_date}: Naver에서 {len(games_raw)}경기 수집")
            if not games_raw:
                logger.info(f"{target_date}: 경기 없음")
                return

            game_ids = await self._upsert_games(db, games_raw)
            logger.info(f"{target_date}: {len(game_ids)}경기 처리됨")

            # 3. 날씨 데이터 수집 → upsert
            await self._upsert_weather(db, games_raw, game_ids)

            await db.commit()
        logger.info(f"ETL 완료: {target_date}")

    async def run_backfill_date(self, target_date: date) -> None:
        """과거 경기 결과 포함 백필용 ETL (fetch_game_results 사용)"""
        logger.info(f"ETL 시작: {target_date}")
        async with AsyncSessionLocal() as db:
            await self._ensure_teams(db)
            games_raw = await self.collector.fetch_game_results(target_date)
            if not games_raw:
                logger.info(f"{target_date}: 경기 없음")
                return
            game_ids = await self._upsert_games(db, games_raw)
            logger.info(f"{target_date}: {len(game_ids)}경기 처리됨")
            if not self.skip_weather:
                await self._upsert_weather(db, games_raw, game_ids)
            await db.commit()
        logger.info(f"ETL 완료: {target_date}")

    async def run_results(self, target_date: date) -> None:
        """경기 결과 업데이트 (전날 결과 수집 용도)"""
        async with AsyncSessionLocal() as db:
            # MLB: DB는 KST 날짜, API는 ET 날짜 기준 → KST 날짜 경기가 ET 기준 전날에 속할 수 있으므로
            # target_date 와 target_date-1 두 날짜를 모두 조회해서 합침
            if self.league == "MLB":
                prev_raw = await self.collector.fetch_game_results(target_date - timedelta(days=1))
                curr_raw = await self.collector.fetch_game_results(target_date)
                # external_game_id 기준 중복 제거
                seen: set[str] = set()
                games_raw = []
                for r in list(prev_raw) + list(curr_raw):
                    key = r.external_game_id or f"{r.home_team_short}_{r.away_team_short}_{r.game_date}"
                    if key not in seen:
                        seen.add(key)
                        games_raw.append(r)
            else:
                games_raw = await self.collector.fetch_game_results(target_date)
            for raw in games_raw:
                if raw.status != "final":
                    continue
                # winner 결정
                winner_short = None
                if raw.home_score is not None and raw.away_score is not None:
                    winner_short = raw.home_team_short if raw.home_score > raw.away_score \
                        else raw.away_team_short

                # games 업데이트: external_game_id 우선 → 팀명 fallback
                stmt = (
                    select(Game)
                    .where(Game.external_game_id == raw.external_game_id)
                    .where(Game.league == raw.league)
                )
                result = await db.execute(stmt)
                game = result.scalar_one_or_none()

                if not game and raw.external_game_id:
                    # external_game_id 없는 기존 경기 → 팀 + 날짜로 매칭
                    home_team = await self._get_team_by_short(db, raw.home_team_short, raw.league)
                    away_team = await self._get_team_by_short(db, raw.away_team_short, raw.league)
                    if home_team and away_team:
                        # raw.game_date는 KST 기준; 기존 DB 경기는 ET 기준(=KST-1)일 수 있어서 둘 다 시도
                        for try_date in [raw.game_date, raw.game_date - timedelta(days=1)]:
                            fallback = await db.execute(
                                select(Game).where(
                                    Game.game_date == try_date,
                                    Game.home_team_id == home_team.id,
                                    Game.away_team_id == away_team.id,
                                    Game.league == raw.league,
                                )
                            )
                            game = fallback.scalar_one_or_none()
                            if game:
                                game.external_game_id = raw.external_game_id
                                # ET 날짜로 저장된 경기를 KST 날짜로 보정
                                if game.game_date != raw.game_date:
                                    game.game_date = raw.game_date
                                break

                if game:
                    game.status = "final"
                    game.home_score = raw.home_score
                    game.away_score = raw.away_score
                    if winner_short:
                        winner = await self._get_team_by_short(db, winner_short, raw.league)
                        if winner:
                            game.winner_team_id = winner.id
                    # predictions.was_correct 업데이트 (항상 재계산)
                    if game.winner_team_id:
                        await db.execute(
                            text("""
                                UPDATE predictions
                                SET was_correct = (predicted_winner_id = :winner_id)
                                WHERE game_id = :game_id
                            """),
                            {"winner_id": game.winner_team_id, "game_id": game.id},
                        )
                    # KBO: 경기 종료 후 Naver 박스스코어 → 자체 선수 스탯 집계
                    if self.league == "KBO":
                        try:
                            from app.pipeline.player_stats_aggregator import ingest_final_game
                            await ingest_final_game(db, game)
                        except Exception as e:
                            logger.warning(f"game_id={game.id} 선수 스탯 집계 실패: {e}")
            await db.commit()
            # Elo 캐시 무효화: 새 결과가 반영됐으므로 다음 예측 시 재빌드
            from app.features.elo_features import invalidate_elo_cache
            invalidate_elo_cache(self.league)

    async def _ensure_teams(self, db: AsyncSession) -> None:
        """팀이 DB에 없으면 삽입 (최초 실행 시)"""
        result = await db.execute(select(Team).where(Team.league == self.league).limit(1))
        if result.scalar_one_or_none():
            return  # 이미 팀 데이터 있음

        teams_raw = await self.collector.fetch_all_teams()
        for raw in teams_raw:
            stmt = pg_insert(Team).values(**normalize_team(raw))
            stmt = stmt.on_conflict_do_update(
                constraint="uq_teams_league_short",
                set_={"name": stmt.excluded.name, "stadium_name": stmt.excluded.stadium_name},
            )
            await db.execute(stmt)
        logger.info(f"{len(teams_raw)}개 팀 upsert 완료")

    async def _upsert_games(
        self, db: AsyncSession, games_raw: list[GameRaw]
    ) -> dict[str, int]:
        """경기 데이터 upsert, external_game_id → games.id 매핑 반환"""
        game_ids: dict[str, int] = {}

        for raw in games_raw:
            home_team = await self._get_team_by_short(db, raw.home_team_short, raw.league)
            away_team = await self._get_team_by_short(db, raw.away_team_short, raw.league)
            if not home_team or not away_team:
                logger.warning(f"팀을 찾을 수 없음: {raw.home_team_short} vs {raw.away_team_short}")
                continue

            winner_id = None
            if raw.home_score is not None and raw.away_score is not None:
                w_short = raw.home_team_short if raw.home_score > raw.away_score \
                    else raw.away_team_short
                winner = await self._get_team_by_short(db, w_short, raw.league)
                winner_id = winner.id if winner else None

            values = normalize_game(
                raw,
                home_team_id=home_team.id,
                away_team_id=away_team.id,
                winner_team_id=winner_id,
            )

            stmt = pg_insert(Game).values(**values)
            # MLB만 game_date 갱신 허용 (ET→KST 변환 필요)
            # KBO/NPB는 game_date 덮어쓰기 금지 (잘못된 날짜로 교체되는 버그 방지)
            game_date_set = (
                stmt.excluded.game_date if raw.league == "MLB"
                else func.coalesce(Game.game_date, stmt.excluded.game_date)
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["league", "external_game_id"],
                index_where=text("external_game_id IS NOT NULL"),
                set_={
                    "home_team_id": stmt.excluded.home_team_id,
                    "away_team_id": stmt.excluded.away_team_id,
                    "game_date": game_date_set,
                    "venue": stmt.excluded.venue,
                    "status": stmt.excluded.status,
                    "home_score": stmt.excluded.home_score,
                    "away_score": stmt.excluded.away_score,
                    "winner_team_id": stmt.excluded.winner_team_id,
                    # NULL이면 기존 값 유지
                    "game_time": func.coalesce(stmt.excluded.game_time, Game.game_time),
                    # NULL이면 기존 값 유지 (라인업 감시기가 넣은 선발 덮어쓰기 방지)
                    "home_starter_name": func.coalesce(stmt.excluded.home_starter_name, Game.home_starter_name),
                    "away_starter_name": func.coalesce(stmt.excluded.away_starter_name, Game.away_starter_name),
                },
            )
            result = await db.execute(stmt)

            # 삽입된 game id 조회
            game = await db.execute(
                select(Game).where(
                    Game.external_game_id == raw.external_game_id,
                    Game.league == raw.league,
                )
            )
            g = game.scalar_one_or_none()
            if g:
                game_ids[raw.external_game_id] = g.id

        return game_ids

    async def _upsert_weather(
        self,
        db: AsyncSession,
        games_raw: list[GameRaw],
        game_ids: dict[str, int],
    ) -> None:
        # 같은 날짜의 같은 구장 좌표는 한 번만 요청 (중복 제거)
        seen_coords: set[tuple] = set()
        for raw in games_raw:
            game_id = game_ids.get(raw.external_game_id)
            if not game_id:
                continue

            coords = _get_team_coords(raw.league, raw.home_team_short)
            if not coords:
                continue

            coord_key = (coords["lat"], coords["lon"], raw.game_date.isoformat())
            already_fetched = coord_key in seen_coords
            seen_coords.add(coord_key)

            weather = await self.weather.fetch_forecast(
                lat=coords["lat"],
                lon=coords["lon"],
                game_date=raw.game_date,
                game_id=game_id,
            )
            # Open-Meteo rate limit 방지: 새 좌표 요청 후 1초 대기
            if not already_fetched:
                await asyncio.sleep(1.0)
            if not weather:
                continue

            weather_values = {k: v for k, v in weather.items() if k != "raw_response"}
            weather_values["game_id"] = game_id
            weather_values["raw_response"] = weather.get("raw_response")
            await db.execute(pg_insert(WeatherLog).values(**weather_values).on_conflict_do_nothing())

    async def refresh_weather_for_game(self, db: AsyncSession, game: "Game") -> None:
        """단일 경기 날씨를 강제 갱신 (캐시 무시)"""
        home_team = await self._get_team_by_short(db, game.home_team.short_name if hasattr(game, 'home_team') else None, game.league) if False else None

        # Game 모델에서 직접 팀 조회
        from app.models import Team
        home_team_result = await db.execute(select(Team).where(Team.id == game.home_team_id))
        home_team = home_team_result.scalar_one_or_none()
        if not home_team:
            return

        coords = _get_team_coords(game.league, home_team.short_name)
        if not coords:
            return

        weather = await self.weather.fetch_forecast(
            lat=coords["lat"],
            lon=coords["lon"],
            game_date=game.game_date,
            game_id=game.id,
            force=True,
        )
        if not weather:
            return

        weather_values = {k: v for k, v in weather.items() if k != "raw_response"}
        weather_values["game_id"] = game.id
        weather_values["raw_response"] = weather.get("raw_response")
        await db.execute(pg_insert(WeatherLog).values(**weather_values).on_conflict_do_nothing())
        await db.commit()
        logger.info(f"game_id={game.id} 날씨 강제 갱신 완료 ({weather.get('weather_main')}, {weather.get('precipitation_mm')}mm)")

    async def _get_team_by_short(
        self, db: AsyncSession, short_name: str, league: str
    ) -> Optional[Team]:
        result = await db.execute(
            select(Team).where(Team.short_name == short_name, Team.league == league)
        )
        return result.scalar_one_or_none()


async def main_async(target_date: date) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    runner = ETLRunner()
    await runner.run_for_date(target_date)


async def backfill_async(start: date, end: date, league: Optional[str] = None, skip_weather: bool = False) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    runner = ETLRunner(league=league, skip_weather=skip_weather)
    current = start
    while current <= end:
        await runner.run_backfill_date(current)
        current += timedelta(days=1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="야구 ETL 파이프라인")
    parser.add_argument("--date", type=str, help="날짜 YYYY-MM-DD (기본: 오늘)")
    parser.add_argument("--backfill", action="store_true", help="백필 모드")
    parser.add_argument("--from", dest="from_date", type=str, help="백필 시작 날짜")
    parser.add_argument("--to", dest="to_date", type=str, help="백필 종료 날짜")
    args = parser.parse_args()

    if args.backfill and args.from_date and args.to_date:
        start = date.fromisoformat(args.from_date)
        end = date.fromisoformat(args.to_date)
        asyncio.run(backfill_async(start, end))
    else:
        target = date.fromisoformat(args.date) if args.date else date.today()
        asyncio.run(main_async(target))
