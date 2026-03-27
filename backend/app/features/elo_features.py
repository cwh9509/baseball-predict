"""
Elo 레이팅 피처
- 시즌 시작 시 평균 회귀 적용 (강팀/약팀 수렴)
- 홈 어드밴티지 보정 포함
- 모듈 레벨 캐시: 학습 중 첫 호출 시 한 번만 DB 조회
"""
import bisect
import logging
from datetime import date
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Game

logger = logging.getLogger(__name__)

INITIAL_ELO = 1500.0
K_FACTOR = 20.0
HOME_ADVANTAGE = 30.0    # 홈팀 이점 보정치 (Elo 포인트)
SEASON_REGRESSION = 0.33  # 시즌 종료 후 평균 회귀율 (33%)

# league -> {team_id: [(date_ordinal, post_game_elo), ...]} 시간순 정렬
_elo_cache: dict[str, dict[int, list[tuple[int, float]]]] = {}


async def get_elo_features(
    db: AsyncSession,
    home_team_id: int,
    away_team_id: int,
    game_date: date,
    league: str,
) -> dict:
    """경기 직전 기준 홈/원정 팀 Elo 레이팅 반환"""
    if league not in _elo_cache:
        await _build_elo_cache(db, league)

    history = _elo_cache[league]
    home_elo = _elo_before(history, home_team_id, game_date)
    away_elo = _elo_before(history, away_team_id, game_date)
    return {
        "home_elo": home_elo,
        "away_elo": away_elo,
        "elo_diff": home_elo - away_elo,
    }


def invalidate_elo_cache(league: Optional[str] = None) -> None:
    """재학습 후 또는 새 경기 결과 반영 시 캐시 초기화"""
    global _elo_cache
    if league:
        _elo_cache.pop(league, None)
    else:
        _elo_cache.clear()


def _elo_before(
    history: dict[int, list[tuple[int, float]]],
    team_id: int,
    cutoff: date,
) -> float:
    """cutoff 날짜 이전 마지막 Elo 반환 (없으면 초기값)"""
    entries = history.get(team_id)
    if not entries:
        return INITIAL_ELO
    keys = [e[0] for e in entries]
    idx = bisect.bisect_left(keys, cutoff.toordinal())
    if idx == 0:
        return INITIAL_ELO
    return entries[idx - 1][1]


async def _build_elo_cache(db: AsyncSession, league: str) -> None:
    """DB의 완료 경기 전체로 Elo 히스토리 계산 후 캐시 저장"""
    result = await db.execute(
        select(Game).where(
            and_(
                Game.league == league,
                Game.status == "final",
                Game.winner_team_id.isnot(None),
            )
        ).order_by(Game.game_date.asc())
    )
    all_games = result.scalars().all()
    logger.info(f"[Elo] {league} {len(all_games)}경기로 캐시 빌드 중...")

    elos: dict[int, float] = {}
    history: dict[int, list[tuple[int, float]]] = {}
    prev_season: Optional[int] = None

    for game in all_games:
        season = game.game_date.year
        h, a = game.home_team_id, game.away_team_id

        # 시즌 교체 시 평균 회귀 (강팀/약팀 격차 완화)
        if prev_season is not None and season != prev_season:
            for tid in list(elos.keys()):
                elos[tid] = elos[tid] + SEASON_REGRESSION * (INITIAL_ELO - elos[tid])
        prev_season = season

        elo_h = elos.get(h, INITIAL_ELO)
        elo_a = elos.get(a, INITIAL_ELO)

        # 홈 어드밴티지 포함 예상 승률
        expected_h = 1 / (1 + 10 ** ((elo_a - elo_h - HOME_ADVANTAGE) / 400))
        actual_h = 1.0 if game.winner_team_id == h else 0.0

        new_h = elo_h + K_FACTOR * (actual_h - expected_h)
        new_a = elo_a + K_FACTOR * ((1 - actual_h) - (1 - expected_h))

        # 경기 후 Elo를 히스토리에 기록 (다음 경기 조회에 사용)
        ord_ = game.game_date.toordinal()
        history.setdefault(h, []).append((ord_, new_h))
        history.setdefault(a, []).append((ord_, new_a))
        elos[h], elos[a] = new_h, new_a

    _elo_cache[league] = history
    logger.info(f"[Elo] 완료: {len(elos)}팀 ({league})")
