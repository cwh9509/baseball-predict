"""
NPB 시즌 스탯 DB 모델 — KBO와 동일한 구조
수동 업로드 또는 npb.jp 스크래핑 기반

테이블:
  npb_pitcher_stats       — 개별 투수 (선발/불펜)
  npb_team_bullpen_stats  — 팀 불펜 집계
  npb_team_batting_stats  — 팀 타선 집계
  npb_team_batting_split_stats — 좌완/우완 상대 OPS 스플릿
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NpbPitcherStat(Base):
    """npb.jp 또는 수동 업로드 기반 NPB 투수 시즌 스탯"""
    __tablename__ = "npb_pitcher_stats"
    __table_args__ = (UniqueConstraint("season", "name", "team_short", name="uq_npb_pitcher"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    team_short: Mapped[str] = mapped_column(String(30), nullable=False)
    era: Mapped[float] = mapped_column(Float, nullable=False)
    whip: Mapped[float] = mapped_column(Float, nullable=False)
    k9: Mapped[float] = mapped_column(Float, nullable=False)
    ip: Mapped[float] = mapped_column(Float, nullable=False)
    gs: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    g: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    handedness: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    recent_era: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recent_whip: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class NpbTeamBullypenStat(Base):
    """NPB 팀 불펜 집계 스탯"""
    __tablename__ = "npb_team_bullpen_stats"
    __table_args__ = (UniqueConstraint("season", "team_short", name="uq_npb_team_bullpen"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    team_short: Mapped[str] = mapped_column(String(30), nullable=False)
    bullpen_era: Mapped[float] = mapped_column(Float, nullable=False)
    bullpen_whip: Mapped[float] = mapped_column(Float, nullable=False)
    bullpen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class NpbTeamBattingStat(Base):
    """NPB 팀 타선 집계 스탯"""
    __tablename__ = "npb_team_batting_stats"
    __table_args__ = (UniqueConstraint("season", "team_short", name="uq_npb_team_batting"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    team_short: Mapped[str] = mapped_column(String(30), nullable=False)
    ops: Mapped[float] = mapped_column(Float, nullable=False)
    wrc_plus: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    k_rate: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class NpbTeamBattingSplitStat(Base):
    """NPB 팀 타선 좌완/우완 상대 OPS 스플릿"""
    __tablename__ = "npb_team_batting_split_stats"
    __table_args__ = (UniqueConstraint("season", "team_short", "split", name="uq_npb_team_batting_split"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    team_short: Mapped[str] = mapped_column(String(30), nullable=False)
    split: Mapped[str] = mapped_column(String(10), nullable=False)
    ops: Mapped[float] = mapped_column(Float, nullable=False)
    pa: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
