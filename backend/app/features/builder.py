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
from app.features.injury_features import get_team_il_features
from app.features.pitcher_features import (
    get_pitcher_features, get_team_rotation_era,
    get_kbo_starter_era, get_kbo_starter_stats, get_kbo_bullpen_stats,
    get_mlb_starter_stats, get_mlb_bullpen_stats,
    get_npb_starter_stats, get_npb_bullpen_stats,
)
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

# KBO 팀 로테이션 ERA + 불펜 ERA + 선발 투구 방향 + 타선 스플릿 OPS + 선발 최근 폼
_KBO_ROTATION_COLUMNS = [
    "home_rotation_era", "away_rotation_era", "rotation_era_diff",
    "home_bullpen_era", "away_bullpen_era", "bullpen_era_diff",
    # 선발투수 투구 방향 (1=좌완, 0=우완, NaN=미확인)
    "home_sp_throws_is_lhp", "away_sp_throws_is_lhp",
    # 상대 선발 투구 방향 기준 팀 타선 스플릿 OPS
    "home_lineup_split_ops", "away_lineup_split_ops", "lineup_split_ops_diff",
    # 선발투수 최근 14일 ERA/WHIP (DB에 없으면 NaN)
    "home_sp_recent_era", "away_sp_recent_era", "sp_recent_era_diff",
    "home_sp_recent_whip", "away_sp_recent_whip",
]

# KBO: 팀 폼 + 팀 로테이션 ERA + 날씨 + 구장
KBO_FEATURE_COLUMNS = _FORM_WEATHER_COLUMNS + _KBO_ROTATION_COLUMNS

# NPB: KBO와 동일 구조 (팀 폼 + 팀 로테이션 ERA + 날씨 + 구장)
NPB_FEATURE_COLUMNS = _FORM_WEATHER_COLUMNS + _KBO_ROTATION_COLUMNS

# MLB 확장 피처: 불펜 + 투구방향 + FIP + 타선스플릿 + 최근폼 (KBO 수준 동등화)
_MLB_EXTENDED_COLUMNS = [
    # 팀 불펜 ERA/WHIP
    "home_bullpen_era", "away_bullpen_era", "bullpen_era_diff",
    "home_bullpen_whip", "away_bullpen_whip",
    # 선발 투구 방향 (1=좌완, 0=우완, NaN=미확인)
    "home_sp_throws_is_lhp", "away_sp_throws_is_lhp",
    # FIP (Fielding Independent Pitching — 수비 무관 투수 지표)
    "home_sp_fip", "away_sp_fip", "sp_fip_diff",
    # 타선 스플릿 OPS (상대 선발 투구방향 기준)
    "home_lineup_split_ops", "away_lineup_split_ops", "lineup_split_ops_diff",
    # 선발투수 최근 3경기 ERA (없으면 시즌 ERA)
    "home_sp_recent_era", "away_sp_recent_era", "sp_recent_era_diff",
]

# MLB 고급 피처: 홈/원정 ERA + 구종/구속 + 부상자 현황
_MLB_ADVANCED_COLUMNS = [
    # 선발투수 홈/원정 분리 ERA (구장 선호도)
    "home_sp_venue_era", "away_sp_venue_era", "sp_venue_era_diff",
    # 구종 비율 & 평균 구속
    "home_sp_fastball_pct", "away_sp_fastball_pct",
    "home_sp_avg_velocity", "away_sp_avg_velocity",
    # 부상자 명단 (IL) — 선수 수 & 가중 영향도
    "home_il_count", "away_il_count",
    "home_il_impact", "away_il_impact",
]

# MLB: 전체 피처 (투수/타자 통계 + 확장 + 고급)
MLB_FEATURE_COLUMNS = _FORM_WEATHER_COLUMNS + _PITCHER_BATTER_COLUMNS + _MLB_EXTENDED_COLUMNS + _MLB_ADVANCED_COLUMNS

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
    home_bullpen_whip = None
    away_bullpen_whip = None

    # MLB 확장 피처용 변수
    home_sp_fip = None
    away_sp_fip = None
    home_sp_throws_mlb = None
    away_sp_throws_mlb = None
    home_sp_recent_era_mlb = None
    away_sp_recent_era_mlb = None

    # MLB 고급 피처용 변수
    home_sp_venue_era = None
    away_sp_venue_era = None
    home_sp_fastball_pct = None
    away_sp_fastball_pct = None
    home_sp_avg_velocity = None
    away_sp_avg_velocity = None
    home_il = {"il_count": float("nan"), "il_impact_score": float("nan")}
    away_il = {"il_count": float("nan"), "il_impact_score": float("nan")}

    if league == "MLB":
        # 팀 객체 조회 (불펜 스탯에 필요)
        home_team = await db.execute(select(Team).where(Team.id == game.home_team_id))
        home_team_obj = home_team.scalar_one_or_none()
        away_team = await db.execute(select(Team).where(Team.id == game.away_team_id))
        away_team_obj = away_team.scalar_one_or_none()

        # 불펜 스탯 (DB)
        if home_team_obj:
            bp = await get_mlb_bullpen_stats(home_team_obj.short_name, season, db)
            if bp:
                home_bullpen_era = bp["era"]
                home_bullpen_whip = bp["whip"]
        if away_team_obj:
            bp = await get_mlb_bullpen_stats(away_team_obj.short_name, season, db)
            if bp:
                away_bullpen_era = bp["era"]
                away_bullpen_whip = bp["whip"]

        # 선발투수 DB 스탯 (FIP, 투구방향, 최근폼)
        async def _mlb_sp_extras(pitcher_id, starter_name, team_obj):
            fip = None
            throws = None
            recent_era = None
            if pitcher_id:
                from app.models import Player as PlayerModel
                p = (await db.execute(select(PlayerModel).where(PlayerModel.id == pitcher_id))).scalar_one_or_none()
                name = (p.name if p else None) or starter_name
                team_s = team_obj.short_name if team_obj else ""
            else:
                name = starter_name
                team_s = team_obj.short_name if team_obj else ""
            if name:
                mlb_stats = await get_mlb_starter_stats(name, team_s, season, db)
                if mlb_stats:
                    fip = mlb_stats.get("fip")
                    throws = mlb_stats.get("handedness")
                    recent_era = mlb_stats.get("recent_era")
            return fip, throws, recent_era

        home_sp_fip, home_sp_throws_mlb, home_sp_recent_era_mlb = await _mlb_sp_extras(
            game.home_starter_id, game.home_starter_name, home_team_obj
        )
        away_sp_fip, away_sp_throws_mlb, away_sp_recent_era_mlb = await _mlb_sp_extras(
            game.away_starter_id, game.away_starter_name, away_team_obj
        )

        # 투구방향: DB > Player 테이블 순서
        if home_sp_throws_mlb:
            home_sp_throws = home_sp_throws_mlb
        if away_sp_throws_mlb:
            away_sp_throws = away_sp_throws_mlb

        # 고급 피처: 홈/원정 ERA, 구종/구속 (이미 _mlb_sp_extras에서 mlb_starter_stats 조회)
        async def _mlb_sp_advanced(pitcher_id, starter_name, team_obj, is_home: bool):
            venue_era = None
            fb_pct = None
            velocity = None
            if pitcher_id or starter_name:
                from app.models import Player as PlayerModel
                name = starter_name
                team_s = team_obj.short_name if team_obj else ""
                if pitcher_id:
                    p = (await db.execute(select(PlayerModel).where(PlayerModel.id == pitcher_id))).scalar_one_or_none()
                    name = (p.name if p else None) or starter_name
                if name:
                    mlb_stats = await get_mlb_starter_stats(name, team_s, season, db)
                    if mlb_stats:
                        venue_era = mlb_stats.get("home_era") if is_home else mlb_stats.get("away_era")
                        fb_pct = mlb_stats.get("fastball_pct")
                        velocity = mlb_stats.get("avg_velocity")
            return venue_era, fb_pct, velocity

        home_sp_venue_era, home_sp_fastball_pct, home_sp_avg_velocity = await _mlb_sp_advanced(
            game.home_starter_id, game.home_starter_name, home_team_obj, is_home=True
        )
        away_sp_venue_era, away_sp_fastball_pct, away_sp_avg_velocity = await _mlb_sp_advanced(
            game.away_starter_id, game.away_starter_name, away_team_obj, is_home=False
        )

        # IL 부상자 피처 (Redis 캐시)
        if home_team_obj:
            home_il = await get_team_il_features(home_team_obj.short_name)
        if away_team_obj:
            away_il = await get_team_il_features(away_team_obj.short_name)

    if league in ("KBO", "NPB"):
        home_team = await db.execute(select(Team).where(Team.id == game.home_team_id))
        home_team_obj = home_team.scalar_one_or_none()
        away_team = await db.execute(select(Team).where(Team.id == game.away_team_id))
        away_team_obj = away_team.scalar_one_or_none()
        if home_team_obj:
            home_rotation_era = await get_team_rotation_era(home_team_obj.short_name, league, season, db=db)
        if away_team_obj:
            away_rotation_era = await get_team_rotation_era(away_team_obj.short_name, league, season, db=db)
        if league == "NPB":
            # NPB 개별 선발투수 스탯
            if home_team_obj and game.home_starter_name:
                _home_npb = await get_npb_starter_stats(
                    game.home_starter_name, home_team_obj.short_name, season, db=db
                )
                if _home_npb and home_sp_throws is None:
                    home_sp_throws = _home_npb.get("handedness")
            if away_team_obj and game.away_starter_name:
                _away_npb = await get_npb_starter_stats(
                    game.away_starter_name, away_team_obj.short_name, season, db=db
                )
                if _away_npb and away_sp_throws is None:
                    away_sp_throws = _away_npb.get("handedness")
            # NPB 불펜
            if home_team_obj:
                bp = await get_npb_bullpen_stats(home_team_obj.short_name, season, db)
                if bp:
                    home_bullpen_era = bp["era"]
            if away_team_obj:
                bp = await get_npb_bullpen_stats(away_team_obj.short_name, season, db)
                if bp:
                    away_bullpen_era = bp["era"]

        if league == "KBO":
            if home_team_obj and game.home_starter_name:
                _home_kbo = await get_kbo_starter_stats(
                    game.home_starter_name, home_team_obj.short_name, season, db=db
                )
                home_sp_era_indiv = _home_kbo.get("era") if _home_kbo else None
                # 투구 방향이 아직 없으면 DB에서 조회
                if home_sp_throws is None:
                    home_sp_throws = await _get_kbo_pitcher_handedness(
                        db, game.home_starter_name, home_team_obj.short_name, season
                    )
            if away_team_obj and game.away_starter_name:
                _away_kbo = await get_kbo_starter_stats(
                    game.away_starter_name, away_team_obj.short_name, season, db=db
                )
                away_sp_era_indiv = _away_kbo.get("era") if _away_kbo else None
                if away_sp_throws is None:
                    away_sp_throws = await _get_kbo_pitcher_handedness(
                        db, game.away_starter_name, away_team_obj.short_name, season
                    )
            # 불펜 ERA + WHIP
            if home_team_obj:
                _home_kbo_bp = await get_kbo_bullpen_stats(home_team_obj.short_name, season, db)
                if _home_kbo_bp:
                    home_bullpen_era = _home_kbo_bp["era"]
                    home_bullpen_whip = _home_kbo_bp.get("whip")
            if away_team_obj:
                _away_kbo_bp = await get_kbo_bullpen_stats(away_team_obj.short_name, season, db)
                if _away_kbo_bp:
                    away_bullpen_era = _away_kbo_bp["era"]
                    away_bullpen_whip = _away_kbo_bp.get("whip")

    # KBO 선발투수 최근 14일 ERA/WHIP
    home_sp_recent_era = None
    away_sp_recent_era = None
    home_sp_recent_whip = None
    away_sp_recent_whip = None
    if league == "KBO":
        if home_team_obj and game.home_starter_name:
            recent = await _get_kbo_starter_recent_stats(db, game.home_starter_name, home_team_obj.short_name, season)
            home_sp_recent_era = recent[0]
            home_sp_recent_whip = recent[1]
        if away_team_obj and game.away_starter_name:
            recent = await _get_kbo_starter_recent_stats(db, game.away_starter_name, away_team_obj.short_name, season)
            away_sp_recent_era = recent[0]
            away_sp_recent_whip = recent[1]

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
        # 팀 불펜 ERA (KBO + MLB 공통)
        "home_bullpen_era": home_bullpen_era,
        "away_bullpen_era": away_bullpen_era,
        "bullpen_era_diff": _safe_diff(home_bullpen_era, away_bullpen_era),
        "home_bullpen_whip": home_bullpen_whip,
        "away_bullpen_whip": away_bullpen_whip,
        # KBO 개인 선발투수 ERA (starter_name 있을 때만 값, 없으면 NaN)
        "home_sp_era_indiv": home_sp_era_indiv,
        "away_sp_era_indiv": away_sp_era_indiv,
        "sp_era_indiv_diff": _safe_diff(home_sp_era_indiv, away_sp_era_indiv),
        # 선발 투구 방향 (1=좌완, 0=우완, NaN=미확인) — KBO + MLB 공통
        "home_sp_throws_is_lhp": (1 if home_sp_throws == "L" else 0) if home_sp_throws else float("nan"),
        "away_sp_throws_is_lhp": (1 if away_sp_throws == "L" else 0) if away_sp_throws else float("nan"),
        # FIP (MLB 확장)
        "home_sp_fip": home_sp_fip,
        "away_sp_fip": away_sp_fip,
        "sp_fip_diff": _safe_diff(home_sp_fip, away_sp_fip),
        # 타선 스플릿 OPS (상대 선발 투구방향 기준) — KBO + MLB 공통
        "home_lineup_split_ops": home_lineup.get("lineup_vs_lhp_ops") if away_sp_throws == "L" else home_lineup.get("lineup_vs_rhp_ops"),
        "away_lineup_split_ops": away_lineup.get("lineup_vs_lhp_ops") if home_sp_throws == "L" else away_lineup.get("lineup_vs_rhp_ops"),
        "lineup_split_ops_diff": _safe_diff(
            home_lineup.get("lineup_vs_lhp_ops") if away_sp_throws == "L" else home_lineup.get("lineup_vs_rhp_ops"),
            away_lineup.get("lineup_vs_lhp_ops") if home_sp_throws == "L" else away_lineup.get("lineup_vs_rhp_ops"),
        ),
        # 선발투수 최근 폼 ERA — KBO(14일), MLB(최근 3경기)
        "home_sp_recent_era": home_sp_recent_era_mlb if league == "MLB" else home_sp_recent_era,
        "away_sp_recent_era": away_sp_recent_era_mlb if league == "MLB" else away_sp_recent_era,
        "sp_recent_era_diff": _safe_diff(
            home_sp_recent_era_mlb if league == "MLB" else home_sp_recent_era,
            away_sp_recent_era_mlb if league == "MLB" else away_sp_recent_era,
        ),
        # KBO 전용 (whip은 KBO만)
        "home_sp_recent_whip": home_sp_recent_whip,
        "away_sp_recent_whip": away_sp_recent_whip,
        # MLB 고급 피처
        "home_sp_venue_era": home_sp_venue_era,
        "away_sp_venue_era": away_sp_venue_era,
        "sp_venue_era_diff": _safe_diff(home_sp_venue_era, away_sp_venue_era),
        "home_sp_fastball_pct": home_sp_fastball_pct,
        "away_sp_fastball_pct": away_sp_fastball_pct,
        "home_sp_avg_velocity": home_sp_avg_velocity,
        "away_sp_avg_velocity": away_sp_avg_velocity,
        "home_il_count": home_il.get("il_count"),
        "away_il_count": away_il.get("il_count"),
        "home_il_impact": home_il.get("il_impact_score"),
        "away_il_impact": away_il.get("il_impact_score"),
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

    # KBO: 개인 투수 스탯이 있으면 snapshot의 imputed 리그 평균 교체 (화면 표시용)
    if league == "KBO":
        if locals().get("_home_kbo"):
            snapshot["home_sp_era_season"] = _home_kbo["era"]
            snapshot["home_sp_whip_season"] = _home_kbo["whip"]
            snapshot["home_sp_k9_season"] = _home_kbo["k9"]
            snapshot["home_sp_era_L3"] = home_sp_recent_era or _home_kbo["era"]
            snapshot["home_sp_is_imputed"] = False
            # 에이스: 개인 ERA가 팀 로테이션 ERA보다 0.5 이상 낮으면
            if home_rotation_era:
                snapshot["home_sp_is_ace"] = int(_home_kbo["era"] < home_rotation_era - 0.5)
            # 피로: 최근 ERA가 시즌 ERA보다 1.0 이상 높으면
            if home_sp_recent_era is not None:
                snapshot["home_sp_is_fatigued"] = int(home_sp_recent_era > _home_kbo["era"] + 1.0)
        if locals().get("_away_kbo"):
            snapshot["away_sp_era_season"] = _away_kbo["era"]
            snapshot["away_sp_whip_season"] = _away_kbo["whip"]
            snapshot["away_sp_k9_season"] = _away_kbo["k9"]
            snapshot["away_sp_era_L3"] = away_sp_recent_era or _away_kbo["era"]
            snapshot["away_sp_is_imputed"] = False
            if away_rotation_era:
                snapshot["away_sp_is_ace"] = int(_away_kbo["era"] < away_rotation_era - 0.5)
            if away_sp_recent_era is not None:
                snapshot["away_sp_is_fatigued"] = int(away_sp_recent_era > _away_kbo["era"] + 1.0)

    # MLB: 에이스/피로 계산 (개인 ERA 기준)
    if league == "MLB":
        # 팀 평균 ERA를 기준으로 에이스 판정
        _home_era = snapshot.get("home_sp_era_season")
        _away_era = snapshot.get("away_sp_era_season")
        _home_recent = snapshot.get("home_sp_recent_era")
        _away_recent = snapshot.get("away_sp_recent_era")
        MLB_AVG_ERA = 4.30
        if _home_era is not None:
            snapshot["home_sp_is_ace"] = int(float(_home_era) < MLB_AVG_ERA - 0.7)
            if _home_recent is not None:
                snapshot["home_sp_is_fatigued"] = int(float(_home_recent) > float(_home_era) + 1.0)
        if _away_era is not None:
            snapshot["away_sp_is_ace"] = int(float(_away_era) < MLB_AVG_ERA - 0.7)
            if _away_recent is not None:
                snapshot["away_sp_is_fatigued"] = int(float(_away_recent) > float(_away_era) + 1.0)

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


async def _get_kbo_pitcher_handedness(db: AsyncSession, name: str, team_short: str, season: int) -> Optional[str]:
    """KBO 투수 투구 방향 조회 (L/R). statiz에서 수집한 handedness 필드."""
    from app.models.kbo_stats import KboPitcherStat
    from sqlalchemy import and_
    for s in [season, season - 1]:
        row = (await db.execute(
            select(KboPitcherStat).where(
                and_(KboPitcherStat.name == name, KboPitcherStat.team_short == team_short,
                     KboPitcherStat.season == s)
            )
        )).scalar_one_or_none()
        if row and row.handedness:
            return row.handedness
    return None


async def _get_kbo_starter_recent_stats(
    db: AsyncSession, name: str, team_short: str, season: int
) -> tuple[Optional[float], Optional[float]]:
    """KBO 선발투수 최근 14일 ERA, WHIP 조회. 없으면 (None, None)"""
    from app.models.kbo_stats import KboPitcherStat
    from sqlalchemy import and_
    for s in [season, season - 1]:
        for cond in [
            and_(KboPitcherStat.name == name, KboPitcherStat.team_short == team_short, KboPitcherStat.season == s),
            and_(KboPitcherStat.name == name, KboPitcherStat.season == s),
        ]:
            row = (await db.execute(select(KboPitcherStat).where(cond))).scalar_one_or_none()
            if row and (row.recent_era is not None or row.recent_whip is not None):
                return row.recent_era, row.recent_whip
    return None, None


async def _get_kbo_bullpen_era(db: AsyncSession, team_short: str, season: int) -> Optional[float]:
    """팀 불펜 ERA 조회 — 개별 투수 데이터(gs<5) 우선, 팀 집계 테이블 폴백"""
    from app.features.pitcher_features import get_kbo_bullpen_stats
    result = await get_kbo_bullpen_stats(team_short, season, db)
    return result["era"] if result else None


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
