"""
팀 폼 피처 계산
최근 N경기 승률, 득실차, 연승/연패, 상대전적
"""
import logging
from datetime import date
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Game, Team

logger = logging.getLogger(__name__)


async def get_team_form_features(
    db: AsyncSession,
    team_id: int,
    as_home: bool,
    cutoff_date: date,  # 경기 시작 전 날짜 (데이터 누수 방지)
    opponent_id: Optional[int] = None,
) -> dict:
    """
    팀 폼 피처 딕셔너리 반환
    prefix: 'home_' 또는 'away_' 로 호출 측에서 붙임
    """
    features = {}

    # 최근 경기 결과 조회 (home + away 모두)
    stmt = (
        select(Game)
        .where(
            and_(
                Game.status == "final",
                Game.game_date < cutoff_date,
                (Game.home_team_id == team_id) | (Game.away_team_id == team_id),
            )
        )
        .order_by(Game.game_date.desc())
        .limit(30)
    )
    result = await db.execute(stmt)
    recent_games = result.scalars().all()

    if not recent_games:
        return _empty_form_features()

    # 각 경기별 승패 계산
    game_results = []
    for g in recent_games:
        if g.winner_team_id is None:
            continue
        won = g.winner_team_id == team_id
        is_home_game = g.home_team_id == team_id
        runs_scored = g.home_score if is_home_game else g.away_score
        runs_allowed = g.away_score if is_home_game else g.home_score
        game_results.append({
            "won": won,
            "is_home": is_home_game,
            "rs": runs_scored or 0,
            "ra": runs_allowed or 0,
            "date": g.game_date,
        })

    if not game_results:
        return _empty_form_features()

    # L5 승률
    last5 = game_results[:5]
    features["win_rate_L5"] = sum(1 for g in last5 if g["won"]) / max(len(last5), 1)

    # L5 득실차 (더 최신 트렌드)
    features["run_diff_L5"] = sum(g["rs"] - g["ra"] for g in last5)

    # L10 승률
    last10 = game_results[:10]
    features["win_rate_L10"] = sum(1 for g in last10 if g["won"]) / max(len(last10), 1)

    # L10 득실차
    features["run_diff_L10"] = sum(g["rs"] - g["ra"] for g in last10)

    # 홈/원정 전용 승률 (최근 10경기 중 해당 장소 경기만)
    home_games = [g for g in last10 if g["is_home"]]
    away_games = [g for g in last10 if not g["is_home"]]
    if as_home:
        features["win_rate_venue_split"] = (
            sum(1 for g in home_games if g["won"]) / len(home_games) if home_games else float("nan")
        )
    else:
        features["win_rate_venue_split"] = (
            sum(1 for g in away_games if g["won"]) / len(away_games) if away_games else float("nan")
        )

    # 최근 7일 경기 수 (일정 과부하 피로도 지표)
    from datetime import timedelta
    cutoff_7d = cutoff_date - timedelta(days=7)
    features["games_L7"] = sum(
        1 for g in game_results if g["date"] >= cutoff_7d
    )

    # 최근 3일 경기 수 (불펜 피로도 프록시 — 3일 이내 연속 경기일수록 불펜 소진)
    cutoff_3d = cutoff_date - timedelta(days=3)
    last3d_games = [g for g in game_results if g["date"] >= cutoff_3d]
    features["games_L3"] = len(last3d_games)

    # 최근 3경기 평균 실점 (불펜 퀄리티 프록시)
    last3 = game_results[:3]
    features["runs_allowed_L3"] = (
        sum(g["ra"] for g in last3) / len(last3) if last3 else float("nan")
    )

    # L30 피타고리안 승률 (RS^1.83 / (RS^1.83 + RA^1.83))
    last30 = game_results[:30]
    rs30 = sum(g["rs"] for g in last30)
    ra30 = sum(g["ra"] for g in last30)
    if rs30 + ra30 > 0:
        rs_exp = rs30 ** 1.83
        ra_exp = ra30 ** 1.83
        features["pythagorean_L30"] = rs_exp / (rs_exp + ra_exp) if (rs_exp + ra_exp) > 0 else 0.5
    else:
        features["pythagorean_L30"] = 0.5

    # 연승/연패 (부호 있음: +3=3연승, -2=2연패)
    streak = 0
    if game_results:
        first_result = game_results[0]["won"]
        for r in game_results:
            if r["won"] == first_result:
                streak += (1 if first_result else -1)
            else:
                break
    features["win_streak"] = streak

    # 상대전적 (최근 2년)
    if opponent_id:
        from datetime import timedelta
        one_year_ago = date(cutoff_date.year - 1, cutoff_date.month, cutoff_date.day)
        h2h_stmt = (
            select(Game)
            .where(
                and_(
                    Game.status == "final",
                    Game.game_date < cutoff_date,
                    Game.game_date >= one_year_ago,
                    (
                        ((Game.home_team_id == team_id) & (Game.away_team_id == opponent_id))
                        | ((Game.home_team_id == opponent_id) & (Game.away_team_id == team_id))
                    ),
                )
            )
            .order_by(Game.game_date.desc())
            .limit(30)
        )
        h2h_result = await db.execute(h2h_stmt)
        h2h_games = h2h_result.scalars().all()
        if len(h2h_games) >= 2:
            h2h_wins = sum(1 for g in h2h_games if g.winner_team_id == team_id)
            features["h2h_win_pct"] = h2h_wins / len(h2h_games)
            # 상대전적 평균 득실차
            run_diffs = []
            for g in h2h_games:
                if g.home_score is None or g.away_score is None:
                    continue
                if g.home_team_id == team_id:
                    run_diffs.append(g.home_score - g.away_score)
                else:
                    run_diffs.append(g.away_score - g.home_score)
            features["h2h_run_diff"] = sum(run_diffs) / len(run_diffs) if run_diffs else 0.0
        else:
            features["h2h_win_pct"] = 0.5
            features["h2h_run_diff"] = 0.0

    return features


def _empty_form_features() -> dict:
    """데이터 없을 때 반환하는 기본값 (NaN 대신 중립값)"""
    return {
        "win_rate_L5": float("nan"),
        "run_diff_L5": float("nan"),
        "win_rate_L10": float("nan"),
        "run_diff_L10": float("nan"),
        "pythagorean_L30": float("nan"),
        "win_streak": float("nan"),
        "win_rate_venue_split": float("nan"),
        "games_L7": float("nan"),
        "games_L3": float("nan"),
        "runs_allowed_L3": float("nan"),
        "h2h_win_pct": float("nan"),
        "h2h_run_diff": float("nan"),
    }


async def get_recent_scoring_trend(
    db: AsyncSession,
    team_id: int,
    cutoff_date: date,
    n: int = 5,
) -> dict:
    """
    최근 N경기 득점 추이
    Returns: {
        "scores": [3, 7, 2, 5, 4],   # 최신→과거 순
        "avg_runs_scored": 4.2,
        "avg_runs_allowed": 3.8,
        "trend": "hot" | "cold" | "normal",  # L3 평균 vs L5 전체 평균
    }
    """
    from app.models import Game

    stmt = (
        select(Game)
        .where(
            and_(
                Game.status == "final",
                Game.game_date < cutoff_date,
                (Game.home_team_id == team_id) | (Game.away_team_id == team_id),
                Game.home_score.isnot(None),
            )
        )
        .order_by(Game.game_date.desc())
        .limit(n)
    )
    result = await db.execute(stmt)
    games = result.scalars().all()

    if not games:
        return {}

    scores = []
    runs_allowed = []
    for g in games:
        is_home = g.home_team_id == team_id
        rs = g.home_score if is_home else g.away_score
        ra = g.away_score if is_home else g.home_score
        scores.append(rs or 0)
        runs_allowed.append(ra or 0)

    avg_rs = sum(scores) / len(scores)
    avg_ra = sum(runs_allowed) / len(runs_allowed)

    # 트렌드: 최근 3경기 평균 득점 vs 전체 평균
    recent3_avg = sum(scores[:3]) / min(3, len(scores))
    if recent3_avg >= avg_rs + 1.5:
        trend = "hot"
    elif recent3_avg <= avg_rs - 1.5:
        trend = "cold"
    else:
        trend = "normal"

    return {
        "scores": scores,
        "avg_runs_scored": round(avg_rs, 2),
        "avg_runs_allowed": round(avg_ra, 2),
        "trend": trend,
    }


async def get_batter_vs_pitcher_stats(
    db: AsyncSession,
    batting_team_id: int,
    pitcher_name: Optional[str],
    league: str,
    cutoff_date: date,
    seasons: int = 2,
) -> dict:
    """
    KBO/MLB: 타선 vs 특정 선발투수 상대전적 (경기 기반 근사)
    선발투수가 등판한 경기에서 해당 타선의 득점 패턴
    Returns: {
        "games": 경기수,
        "avg_runs_scored": 평균 득점,
        "win_rate": 승률,
    }
    """
    from app.models import Game
    from sqlalchemy import or_

    if not pitcher_name:
        return {}

    cutoff_start = date(cutoff_date.year - seasons, cutoff_date.month, cutoff_date.day)

    stmt = (
        select(Game)
        .where(
            and_(
                Game.status == "final",
                Game.game_date < cutoff_date,
                Game.game_date >= cutoff_start,
                Game.league == league,
                or_(
                    # 타선이 홈팀, 상대 선발이 원정 선발
                    and_(
                        Game.home_team_id == batting_team_id,
                        Game.away_starter_name == pitcher_name,
                    ),
                    # 타선이 원정팀, 상대 선발이 홈 선발
                    and_(
                        Game.away_team_id == batting_team_id,
                        Game.home_starter_name == pitcher_name,
                    ),
                ),
                Game.home_score.isnot(None),
            )
        )
        .order_by(Game.game_date.desc())
        .limit(20)
    )
    result = await db.execute(stmt)
    games = result.scalars().all()

    if not games:
        return {}

    total_rs = 0
    wins = 0
    for g in games:
        is_home = g.home_team_id == batting_team_id
        rs = g.home_score if is_home else g.away_score
        won = g.winner_team_id == batting_team_id
        total_rs += (rs or 0)
        if won:
            wins += 1

    n = len(games)
    return {
        "games": n,
        "avg_runs_scored": round(total_rs / n, 2),
        "win_rate": round(wins / n, 3),
    }
