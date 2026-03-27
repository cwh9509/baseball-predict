from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Integer, Numeric, SmallInteger, String, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base


class WeatherLog(Base):
    __tablename__ = "weather_logs"

    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    fetched_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"), nullable=False)
    is_forecast = Column(Boolean, server_default="true", nullable=False)  # True=예보, False=실측
    temperature_c = Column(Numeric(5, 2))
    feels_like_c = Column(Numeric(5, 2))
    humidity_pct = Column(SmallInteger)
    wind_speed_ms = Column(Numeric(5, 2))
    wind_deg = Column(SmallInteger)
    wind_direction = Column(String(5))          # N, NNE, NE, ...
    precipitation_mm = Column(Numeric(6, 2), server_default="0")
    cloud_cover_pct = Column(SmallInteger)
    visibility_m = Column(Integer)
    weather_main = Column(String(50))           # Clear, Rain, Clouds, ...
    weather_desc = Column(String(100))
    uv_index = Column(Numeric(4, 1))
    raw_response = Column(JSONB)                # OpenWeatherMap 전체 응답 보관

    __table_args__ = (
        CheckConstraint("humidity_pct BETWEEN 0 AND 100", name="chk_weather_humidity"),
        CheckConstraint("wind_deg BETWEEN 0 AND 360", name="chk_weather_wind_deg"),
        CheckConstraint("cloud_cover_pct BETWEEN 0 AND 100", name="chk_weather_cloud"),
    )
