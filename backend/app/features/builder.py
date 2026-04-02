"""
피처 벡터 조합기 — 모든 피처 모듈을 통합

핵심 규칙:
  1. cutoff_date = game.game_date (경기 시작 전 데이터만 사용)
  2. 누락 데이터 → float('nan') (XGBoost가 자체 처리)
  3. 점수/승패 관련 컬럼 절대 포함 금지 (데이터 누수)

컬럼 순서는 모델 직렬화 시 고정됨 — 변경 시 모델 재학습 필요
"""
import logging
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.ballpark_features import get_ballpark_features
from app.features.batter_features import get_lineup_features
from app.features.elo_features import get_elo_features
from app.features.pitcher_features import get_pitcher_features, get_team_rotation_era, get_kbo_starter_era
from app.features.team_features import get_team_form_features
from app.features.weather_features import get_weather_features
from app.models import Game, Player, Team

logger = logging.getLogger(__name__)

# 팀 폼 + 날씨 + 구장 (KBO용 — 투수/타자 통계 없음)
_FORM_WEATHER_COLUMNS = [
    # 홈팀 폼
    "home_win_rate_L5", "home_run_diff_L5",
    "home_win_rate_L10", "home_run_diff_L10",
    "home_pythagorean_L30", "home_win_streak",
    "home_win_rate_home_only", "home_games_L7",
    # 홈팀 불펜 피로도
    "home_games_L3", "home_runs_allowed_L3",
    # 원정팀 폼
    "away_win_rate_L5", "away_run_diff_L5",
    "away_win_rate_L10", "away_run_diff_L10",
    "away_pythagorean_L30", "away_win_streak",
    "away_win_rate_away_only", "away_games_L7",
    # 원정팀 불펜 피로도
    "away_games_L3", "away_runs_allowed_L3",
    # 상대전적 (최근 2년)
    "h2h_win_pct_home", "h2h_run_diff_home",
    # Elo 레이팅
    "elo_diff",
    # 날씨
    "temperature_c", "is_hot", "is_cold", "wind_speed_ms",
    "wind_favor_home", "wind_favor_pitcher", "is_raining",
    "humidity_pct", "is_dome_game",
    # 구장/컨텍스트
    "park_factor", "game_month", "is_day_game", "days_since_season_start",
]

# 투수 + 타선 피처 (MLB용 — 실제 통계 있음)
_PITCHER_BATTER_COLUMNS = [
    # 홈 선발투수
    "home_sp_era_season", "home_sp_whip_season", "home_sp_k9_season",
    "home_sp_days_rest", "home_sp_era_L3", "home_sp_is_ace",
    "home_sp_is_fatigued", "home_sp_is_imputed",
    # 원정 선발투수
    "away_sp_era_season", "away_sp_whip_season", "away_sp_k9_season",
    "away_sp_days_rest", "away_sp_era_L3", "away_sp_is_ace",
    "away_sp_is_fatigued", "away_sp_is_imputed",
    # 파생 (투수)
    "sp_era_diff",
    # 홈 타선
    "home_lineup_ops", "home_lineup_wrc_plus", "home_lineup_k_rate",
    "home_lineup_effective_ops",
    # 원정 타선
    "away_lineup_ops", "away_lineup_wrc_plus", "away_lineup_k_rate",
    "away_lineup_effective_ops",
    # 파생 (타선)
    "lineup_ops_diff",
]

# KBO 팀 로테이션 ERA + 불펜 ERA
_KBO_ROTATION_COLUMNS = [
    "home_rotation_era", "away_rotation_era", "rotation_era_diff",
    "home_bullpen_era", "away_bullpen_era", "bullpen_era_diff",
]

# KBO: 팀 폼 + 팀 로테이션 ERA + 날씨 + 구장
KBO_FEATURE_COLUMNS = _FORM_WEATHER_COLUMNS + _KBO_ROTATION_COLUMNS

# NPB: KBO와 동일 구조 (팀 폼 + 팀 로테이션 ERA + 날씨 + 구장)
NPB_FEATURE_COLUMNS = _FORM_WEATHER_COLUMNS + _KBO_ROTATION_COLUMNS

# MLB: 전체 피처 (투수/타자 통계 포함)
MLB_FEATURE_COLUMNS = _FORM_WEATHER_COLUMNS + _PITCHER_BATTER_COLUMNS

# 기본값 (하위 호환)
FEATURE_COLUMNS = MLB_FEATURE_COLUMNS


def get_feature_columns(league: str) -> list[str]:
    if league == "KBO":
        return KBO_FEATURE_COLUMNS
    if league == "NPB":
        return NPB_FEATURE_COLUMNS
    return MLB_FEATURE_COLUMNS


class FeatureNotReadyError(Exception):
    """필수 피처 데이터가 아직 준비되지 않음"""
    pass


async def build_features(db: AsyncSession, game_id: int) -> tuple[np.ndarray, dict]:
    """
    game_id에 대한 피처 벡터와 스냅샷 딕셔너리 반환

    Returns:
        (feature_array, feature_snapshot)
        feature_array: FEATURE_COLUMNS 순서의 numpy 배열
        feature_snapshot: 로깅/LLM 설명용 딕셔너리
    """
    game_result = await db.execute(select(Game).where(Game.id == game_id))
    game = game_result.scalar_one_or_none()
    if not game:
        raise FeatureNotReadyError(f"game_id {game_id}를 찾을 수 없음")

    cutoff_date: date = game.game_date
    season = cutoff_date.year
    league = game.league

    # 선발투수 투구 방향 조회 (타선 피처에 필요)
    home_sp_throws = await _get_pitcher_throws(db, game.home_starter_id)
    away_sp_throws = await _get_pitcher_throws(db, game.away_starter_id)

    # KBO/NPB 팀 로테이션 ERA (MLB는 개별 투수 stats 사용)
    home_rotation_era = None
    away_rotation_era = None
    home_sp_era_indiv = None
    away_sp_era_indiv = None
    home_team_obj = None
    away_team_obj = None
    home_bullpen_era = None
    away_bullpen_era = None
    if league in ("KBO", "NPB"):
        home_team = await db.execute(select(Team).where(Team.id == game.home_team_id))
        home_team_obj = home_team.scalar_one_or_none()
        away_team = await db.execute(select(Team).where(Team.id == game.away_team_id))
        away_team_obj = away_team.scalar_one_or_none()
        if home_team_obj:
            home_rotation_era = await get_team_rotation_era(home_team_obj.short_name, league, season, db=db)
        if away_team_obj:
            away_rotation_era = await get_team_rotation_era(away_team_obj.short_name, league, season, db=db)
        if league == "KBO":
            if home_team_obj and game.home_starter_name:
                home_sp_era_indiv = await get_kbo_starter_era(
                    game.home_starter_name, home_team_obj.short_name, season, db=db
                )
            if away_team_obj and game.away_starter_name:
                away_sp_era_indiv = await get_kbo_starter_era(
                    game.away_starter_name, away_team_obj.short_name, season, db=db
                )
            # 불펜 ERA
            if home_team_obj:
                home_bullpen_era = await _get_kbo_bullpen_era(db, home_team_obj.short_name, season)
            if away_team_obj:
                away_bullpen_era = await _get_kbo_bullpen_era(db, away_team_obj.short_name, season)

    # --- 피처 수집 (병렬 가능하지만 단순화를 위해 순차 실행) ---
    home_form = await get_team_form_features(
        db, game.home_team_id, as_home=True, cutoff_date=cutoff_date,
        opponent_id=game.away_team_id,
    )
    away_form = await get_team_form_features(
        db, game.away_team_id, as_home=False, cutoff_date=cutoff_date,
        opponent_id=game.home_team_id,
    )
    home_pitcher = await get_pitcher_features(
        db, game.home_starter_id, league, cutoff_date, season
    )
    away_pitcher = await get_pitcher_features(
        db, game.away_starter_id, league, cutoff_date, season
    )
    home_lineup = await get_lineup_features(
        db, game.home_team_id, league, season,
        opponent_starter_throws=away_sp_throws,
    )
    away_lineup = await get_lineup_features(
        db, game.away_team_id, league, season,
        opponent_starter_throws=home_sp_throws,
    )
    weather = await get_weather_features(db, game.id, game.home_team_id)
    ballpark = await get_ballpark_features(db, game)
    elo = await get_elo_features(db, game.home_team_id, game.away_team_id, cutoff_date, league)

    # --- 피처 딕셔너리 조합 ---
    snapshot = {
        # 홈팀 폼
        "home_win_rate_L5": home_form.get("win_rate_L5"),
        "home_run_diff_L5": home_form.get("run_diff_L5"),
        "home_win_rate_L10": home_form.get("win_rate_L10"),
        "home_run_diff_L10": home_form.get("run_diff_L10"),
        "home_pythagorean_L30": home_form.get("pythagorean_L30"),
        "home_win_streak": home_form.get("win_streak"),
        "home_win_rate_home_only": home_form.get("win_rate_venue_split"),
        "home_games_L7": home_form.get("games_L7"),
        "home_games_L3": home_form.get("games_L3"),
        "home_runs_allowed_L3": home_form.get("runs_allowed_L3"),
        # 원정팀 폼
        "away_win_rate_L5": away_form.get("win_rate_L5"),
        "away_run_diff_L5": away_form.get("run_diff_L5"),
        "away_win_rate_L10": away_form.get("win_rate_L10"),
        "away_run_diff_L10": away_form.get("run_diff_L10"),
        "away_pythagorean_L30": away_form.get("pythagorean_L30"),
        "away_win_streak": away_form.get("win_streak"),
        "away_win_rate_away_only": away_form.get("win_rate_venue_split"),
        "away_games_L7": away_form.get("games_L7"),
        "away_games_L3": away_form.get("games_L3"),
        "away_runs_allowed_L3": away_form.get("runs_allowed_L3"),
        # 상대전적 (최근 2년)
        "h2h_win_pct_home": home_form.get("h2h_win_pct", 0.5),
        "h2h_run_diff_home": home_form.get("h2h_run_diff", 0.0),
        # Elo 레이팅
        "elo_diff": elo.get("elo_diff"),
        # 홈 선발투수
        "home_sp_era_season": home_pitcher.get("era_season"),
        "home_sp_whip_season": home_pitcher.get("whip_season"),
        "home_sp_k9_season": home_pitcher.get("k9_season"),
        "home_sp_days_rest": home_pitcher.get("days_rest"),
        "home_sp_era_L3": home_pitcher.get("era_L3"),
        "home_sp_is_ace": int(home_pitcher.get("is_ace", False)),
        "home_sp_is_fatigued": int(home_pitcher.get("is_fatigued", False)),
        "home_sp_is_imputed": int(home_pitcher.get("is_imputed_pitcher", False)),
        # 원정 선발투수
        "away_sp_era_season": away_pitcher.get("era_season"),
        "away_sp_whip_season": away_pitcher.get("whip_season"),
        "away_sp_k9_season": away_pitcher.get("k9_season"),
        "away_sp_days_rest": away_pitcher.get("days_rest"),
        "away_sp_era_L3": away_pitcher.get("era_L3"),
        "away_sp_is_ace": int(away_pitcher.get("is_ace", False)),
        "away_sp_is_fatigued": int(away_pitcher.get("is_fatigued", False)),
        "away_sp_is_imputed": int(away_pitcher.get("is_imputed_pitcher", False)),
        # 파생 (투수)
        "sp_era_diff": _safe_diff(
            home_pitcher.get("era_season"), away_pitcher.get("era_season")
        ),
        # 홈 타선
        "home_lineup_ops": home_lineup.get("lineup_ops_mean"),
        "home_lineup_wrc_plus": home_lineup.get("lineup_wrc_plus"),
        "home_lineup_k_rate": home_lineup.get("lineup_k_rate"),
        "home_lineup_effective_ops": home_lineup.get("effective_ops"),
        # 원정 타선
        "away_lineup_ops": away_lineup.get("lineup_ops_mean"),
        "away_lineup_wrc_plus": away_lineup.get("lineup_wrc_plus"),
        "away_lineup_k_rate": away_lineup.get("lineup_k_rate"),
        "away_lineup_effective_ops": away_lineup.get("effective_ops"),
        # 파생 (타선)
        "lineup_ops_diff": _safe_diff(
            home_lineup.get("effective_ops"), away_lineup.get("effective_ops")
        ),
        # KBO 팀 로테이션 ERA
        "home_rotation_era": home_rotation_era,
        "away_rotation_era": away_rotation_era,
        "rotation_era_diff": _safe_diff(home_rotation_era, away_rotation_era),
        # KBO 팀 불펜 ERA
        "home_bullpen_era": home_bullpen_era,
        "away_bullpen_era": away_bullpen_era,
        "bullpen_era_diff": _safe_diff(home_bullpen_era, away_bullpen_era),
        # KBO 개인 선발투수 ERA (starter_name 있을 때만 값, 없으면 NaN)
        "home_sp_era_indiv": home_sp_era_indiv,
        "away_sp_era_indiv": away_sp_era_indiv,
        "sp_era_indiv_diff": _safe_diff(home_sp_era_indiv, away_sp_era_indiv),
        # 날씨
        "temperature_c": weather.get("temperature_c"),
        "is_hot": int(weather.get("is_hot", False)),
        "is_cold": int(weather.get("is_cold", False)),
        "wind_speed_ms": weather.get("wind_speed_ms"),
        "wind_favor_home": int(weather.get("wind_favor_home", False)),
        "wind_favor_pitcher": int(weather.get("wind_favor_pitcher", False)),
        "is_raining": int(weather.get("is_raining", False)),
        "humidity_pct": weather.get("humidity_pct"),
        "is_dome_game": int(weather.get("is_dome_game", False)),
        # 구장/컨텍스트
        "park_factor": ballpark.get("park_factor"),
        "game_month": ballpark.get("game_month"),
        "is_day_game": int(ballpark.get("is_day_game", False)),
        "days_since_season_start": ballpark.get("days_since_season_start"),
    }

    # 누수 방지 검사: 점수/승패 컬럼 포함 시 오류
    _assert_no_leakage(snapshot)

    # 리그별 피처 컬럼 선택 (KBO는 투수/타자 제외)
    cols = get_feature_columns(league)
    feature_array = np.array(
        [_to_float(snapshot.get(col)) for col in cols],
        dtype=np.float32,
    )

    return feature_array, snapshot


def _safe_diff(a, b) -> float:
    if a is None or b is None:
        return float("nan")
    try:
        return float(a) - float(b)
    except (TypeError, ValueError):
        return float("nan")


def _to_float(val) -> float:
    if val is None:
        return float("nan")
    try:
        return float(val)
    except (TypeError, ValueError):
        return float("nan")


async def _get_kbo_bullpen_era(db: AsyncSession, team_short: str, season: int) -> Optional[float]:
    """DB에서 팀 불펜 ERA 조회 (현 시즌 없으면 직전 시즌 폴백)"""
    from app.models.kbo_stats import KboTeamBullypenStat
    from sqlalchemy import and_
    for s in [season, season - 1]:
        row = (await db.execute(
            select(KboTeamBullypenStat).where(
                and_(KboTeamBullypenStat.team_short == team_short, KboTeamBullypenStat.season == s)
            )
        )).scalar_one_or_none()
        if row:
            return row.bullpen_era
    return None


async def _get_pitcher_throws(db: AsyncSession, pitcher_id) -> Optional[str]:
    if pitcher_id is None:
        return None
    result = await db.execute(select(Player).where(Player.id == pitcher_id))
    p = result.scalar_one_or_none()
    return p.throws if p else None


LEAKAGE_KEYWORDS = {"score", "winner", "result", "actual", "final", "was_correct"}


def _assert_no_leakage(snapshot: dict) -> None:
    for key in snapshot.keys():
        for kw in LEAKAGE_KEYWORDS:
            if kw in key.lower():
                raise ValueError(
                    f"데이터 누수 감지! 피처 키에 '{kw}'가 포함됨: '{key}'"
                )
