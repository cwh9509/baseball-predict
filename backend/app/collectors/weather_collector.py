"""
날씨 데이터 수집기 — Open-Meteo (무료, API 키 불필요)
구장 좌표 기준으로 기온·풍속·강수량·구름 등을 수집
Redis에 시간당 캐시하여 중복 API 호출 방지
"""
import logging
from datetime import date, datetime, timezone
from typing import Optional

import httpx

from app.core.redis_client import cache_get, cache_set

logger = logging.getLogger(__name__)

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# WMO weather code → (main, description)
WMO_CODES: dict[int, tuple[str, str]] = {
    0:  ("Clear",       "Clear sky"),
    1:  ("Clear",       "Mainly clear"),
    2:  ("Clouds",      "Partly cloudy"),
    3:  ("Clouds",      "Overcast"),
    45: ("Fog",         "Fog"),
    48: ("Fog",         "Icy fog"),
    51: ("Drizzle",     "Light drizzle"),
    53: ("Drizzle",     "Moderate drizzle"),
    55: ("Drizzle",     "Dense drizzle"),
    61: ("Rain",        "Slight rain"),
    63: ("Rain",        "Moderate rain"),
    65: ("Rain",        "Heavy rain"),
    71: ("Snow",        "Slight snow"),
    73: ("Snow",        "Moderate snow"),
    75: ("Snow",        "Heavy snow"),
    80: ("Rain",        "Slight showers"),
    81: ("Rain",        "Moderate showers"),
    82: ("Rain",        "Violent showers"),
    95: ("Thunderstorm","Thunderstorm"),
    96: ("Thunderstorm","Thunderstorm with hail"),
    99: ("Thunderstorm","Thunderstorm with heavy hail"),
}

WIND_DIRECTIONS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                   "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def deg_to_direction(deg: float) -> str:
    idx = round(deg / 22.5) % 16
    return WIND_DIRECTIONS[idx]


class WeatherCollector:

    def __init__(self):
        pass  # API 키 불필요

    async def fetch_forecast(
        self,
        lat: float,
        lon: float,
        game_date: date,
        game_id: int,
    ) -> Optional[dict]:
        cache_key = f"weather:{lat:.4f}:{lon:.4f}:{game_date.isoformat()}"
        cached = await cache_get(cache_key)
        if cached:
            return cached

        try:
            today = date.today()
            is_historical = game_date < today

            async with httpx.AsyncClient(timeout=10.0) as client:
                if is_historical:
                    resp = await client.get(
                        OPEN_METEO_ARCHIVE_URL,
                        params={
                            "latitude": lat,
                            "longitude": lon,
                            "start_date": game_date.isoformat(),
                            "end_date": game_date.isoformat(),
                            "daily": ",".join([
                                "temperature_2m_max",
                                "apparent_temperature_max",
                                "precipitation_sum",
                                "wind_speed_10m_max",
                                "wind_direction_10m_dominant",
                                "cloud_cover_mean",
                                "weather_code",
                            ]),
                            "hourly": "relative_humidity_2m",
                            "timezone": "Asia/Seoul",
                        },
                    )
                else:
                    resp = await client.get(
                        OPEN_METEO_FORECAST_URL,
                        params={
                            "latitude": lat,
                            "longitude": lon,
                            "daily": ",".join([
                                "temperature_2m_max",
                                "apparent_temperature_max",
                                "precipitation_sum",
                                "precipitation_probability_max",
                                "wind_speed_10m_max",
                                "wind_direction_10m_dominant",
                                "cloud_cover_mean",
                                "weather_code",
                                "uv_index_max",
                            ]),
                            "hourly": "relative_humidity_2m",
                            "timezone": "Asia/Seoul",
                            "forecast_days": 10,
                        },
                    )
                resp.raise_for_status()
                raw = resp.json()

            weather = self._extract_daily(raw, game_date, game_id)
            if weather:
                await cache_set(cache_key, weather, ttl=3600)
            return weather

        except httpx.HTTPStatusError as e:
            logger.error(f"Open-Meteo API 오류 ({lat},{lon}): {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"날씨 수집 실패 ({lat},{lon}): {e}")
            return None

    def _extract_daily(self, raw: dict, game_date: date, game_id: int) -> Optional[dict]:
        daily = raw.get("daily", {})
        dates = daily.get("time", [])

        date_str = game_date.isoformat()
        if date_str not in dates:
            logger.warning(f"날씨 데이터 없음: {game_date}")
            return None

        idx = dates.index(date_str)

        def get(key):
            vals = daily.get(key, [])
            return vals[idx] if idx < len(vals) else None

        # 경기 시간대(12~18시) 평균 습도 계산
        humidity = self._hourly_mean(raw, game_date, "relative_humidity_2m", 12, 18)

        wind_deg = get("wind_direction_10m_dominant") or 0
        wmo_code = get("weather_code") or 0
        main, desc = WMO_CODES.get(wmo_code, ("Unknown", f"WMO {wmo_code}"))

        wind_kmh = get("wind_speed_10m_max") or 0
        wind_ms = round(wind_kmh / 3.6, 2)  # km/h → m/s

        result = {
            "game_id": game_id,
            "is_forecast": True,
            "temperature_c": get("temperature_2m_max"),
            "feels_like_c": get("apparent_temperature_max"),
            "humidity_pct": humidity,
            "wind_speed_ms": wind_ms,
            "wind_deg": wind_deg,
            "wind_direction": deg_to_direction(wind_deg),
            "precipitation_mm": get("precipitation_sum") or 0,
            "cloud_cover_pct": get("cloud_cover_mean"),
            "weather_main": main,
            "weather_desc": desc,
            "uv_index": get("uv_index_max"),
            "raw_response": {
                "wmo_code": wmo_code,
                "precip_prob_pct": get("precipitation_probability_max"),
                "source": "open-meteo",
            },
        }
        return result

    def _hourly_mean(
        self, raw: dict, game_date: date, field: str, hour_from: int, hour_to: int
    ) -> Optional[float]:
        hourly = raw.get("hourly", {})
        times = hourly.get("time", [])
        values = hourly.get(field, [])
        prefix = game_date.isoformat()

        samples = [
            values[i]
            for i, t in enumerate(times)
            if t.startswith(prefix)
            and i < len(values)
            and values[i] is not None
            and hour_from <= int(t[11:13]) < hour_to
        ]
        if not samples:
            return None
        return round(sum(samples) / len(samples), 1)
