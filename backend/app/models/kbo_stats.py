from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class KboPitcherStat(Base):
    """statiz에서 수집한 KBO 투수 시즌 스탯 (로컬에서 업로드)"""
    __tablename__ = "kbo_pitcher_stats"
    __table_args__ = (UniqueConstraint("season", "name", "team_short", name="uq_kbo_pitcher"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    team_short: Mapped[str] = mapped_column(String(20), nullable=False)
    era: Mapped[float] = mapped_column(Float, nullable=False)
    whip: Mapped[float] = mapped_column(Float, nullable=False)
    k9: Mapped[float] = mapped_column(Float, nullable=False)
    ip: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class KboTeamBattingStat(Base):
    """statiz에서 수집한 KBO 팀 타선 스탯 (로컬에서 업로드)"""
    __tablename__ = "kbo_team_batting_stats"
    __table_args__ = (UniqueConstraint("season", "team_short", name="uq_kbo_team_batting"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    team_short: Mapped[str] = mapped_column(String(20), nullable=False)
    ops: Mapped[float] = mapped_column(Float, nullable=False)
    wrc_plus: Mapped[float] = mapped_column(Float, nullable=False)
    k_rate: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
