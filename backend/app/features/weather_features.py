"""
날씨 피처 계산
기온, 풍속, 강수여부, 돔구장 여부, 바람 방향 유불리
"""
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Team, WeatherLog

logger = logging.getLogger(__name__)

# 야구 경기 영향 임계값
HOT_TEMP_C = 32.0      # 더운 날 (공이 더 멀리 날아감)
COLD_TEMP_C = 10.0     # 추운 날 (투수 그립 불안정)
RAIN_THRESHOLD_MM = 0.5


async def get_weather_features(
    db: AsyncSession,
    game_id: int,
    home_team_id: int,
) -> dict:
    """날씨 피처 반환"""
    # 홈팀 구장 정보 조회
    team_result = await db.execute(select(Team).where(Team.id == home_team_id))
    home_team = team_result.scalar_one_or_none()

    # 돔구장이면 날씨 피처 전체 무효
    is_dome = (home_team.roof_type == "dome") if home_team else False
    if is_dome:
        return _dome_features()

    # weather_logs에서 최신 예보 조회
    weather_result = await db.execute(
        select(WeatherLog)
        .where(WeatherLog.game_id == game_id)
        .order_by(WeatherLog.fetched_at.desc())
        .limit(1)
    )
    weather = weather_result.scalar_one_or_none()

    if not weather:
        return _missing_weather_features(is_dome=False)

    temp = float(weather.temperature_c or 20.0)
    wind_ms = float(weather.wind_speed_ms or 0.0)
    wind_deg = float(weather.wind_deg or 0.0)
    precip = float(weather.precipitation_mm or 0.0)
    humidity = int(weather.humidity_pct or 50)

    return {
        "temperature_c": temp,
        "is_hot": temp > HOT_TEMP_C,
        "is_cold": temp < COLD_TEMP_C,
        "wind_speed_ms": wind_ms,
        "wind_favor_home": _wind_favor_hitter(wind_deg),   # 타자 유리 방향 (CF 방향)
        "wind_favor_pitcher": _wind_favor_pitcher(wind_deg), # 투수 유리 방향 (홈플레이트로)
        "is_raining": precip > RAIN_THRESHOLD_MM,
        "precipitation_mm": precip,
        "humidity_pct": humidity,
        "is_dome_game": False,
    }


def _wind_favor_hitter(wind_deg: float) -> bool:
    """
    바람이 센터필드 방향(약 0도 = 북쪽)으로 불면 타자 유리
    실제로는 구장별로 방향이 달라 단순화한 근사치
    """
    # 풍향 315~45도 (북쪽 ± 45도): 대부분 구장에서 CF 방향
    return (wind_deg >= 315 or wind_deg <= 45)


def _wind_favor_pitcher(wind_deg: float) -> bool:
    """바람이 홈플레이트 방향으로 불면 투수 유리 (정면 역풍)"""
    return 135 <= wind_deg <= 225


def _dome_features() -> dict:
    return {
        "temperature_c": 22.0,   # 돔 내부 평균 온도
        "is_hot": False,
        "is_cold": False,
        "wind_speed_ms": 0.0,
        "wind_favor_home": False,
        "wind_favor_pitcher": False,
        "is_raining": False,
        "precipitation_mm": 0.0,
        "humidity_pct": 50,
        "is_dome_game": True,
    }


def _missing_weather_features(is_dome: bool) -> dict:
    return {
        "temperature_c": float("nan"),
        "is_hot": False,
        "is_cold": False,
        "wind_speed_ms": float("nan"),
        "wind_favor_home": False,
        "wind_favor_pitcher": False,
        "is_raining": False,
        "precipitation_mm": float("nan"),
        "humidity_pct": float("nan"),
        "is_dome_game": is_dome,
    }
