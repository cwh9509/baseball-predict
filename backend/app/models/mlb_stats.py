"""
MLB 시즌 스탯 DB 모델
pybaseball(FanGraphs) 데이터 기반 — mlb_stats_collector.py 가 주기적으로 upsert

테이블:
  mlb_pitcher_stats       — 개별 투수 (선발/불펜 포함)
  mlb_team_bullpen_stats  — 팀 불펜 집계
  mlb_team_batting_stats  — 팀 타선 집계
  mlb_team_batting_split_stats — 좌완/우완 상대 팀 타선 OPS 스플릿
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MlbPitcherStat(Base):
    """FanGraphs에서 수집한 MLB 투수 시즌 스탯 (선발+불펜 모두 포함)"""
    __tablename__ = "mlb_pitcher_stats"
    __table_args__ = (UniqueConstraint("season", "name", "team_short", name="uq_mlb_pitcher"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    team_short: Mapped[str] = mapped_column(String(10), nullable=False)
    era: Mapped[float] = mapped_column(Float, nullable=False)
    fip: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # Fielding Independent Pitching
    whip: Mapped[float] = mapped_column(Float, nullable=False)
    k9: Mapped[float] = mapped_column(Float, nullable=False)
    bb9: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ip: Mapped[float] = mapped_column(Float, nullable=False)
    gs: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)    # games started (0=불펜)
    g: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)     # 총 등판수
    handedness: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)  # "L" or "R"
    recent_era: Mapped[Optional[float]] = mapped_column(Float, nullable=True)    # 최근 3경기 ERA
    recent_whip: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # 최근 3경기 WHIP
    fg_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)      # FanGraphs 선수 ID
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class MlbTeamBullypenStat(Base):
    """MLB 팀 불펜 집계 스탯 (GS=0 또는 GS/G < 0.3 인 투수 IP 가중 평균)"""
    __tablename__ = "mlb_team_bullpen_stats"
    __table_args__ = (UniqueConstraint("season", "team_short", name="uq_mlb_team_bullpen"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    team_short: Mapped[str] = mapped_column(String(10), nullable=False)
    bullpen_era: Mapped[float] = mapped_column(Float, nullable=False)
    bullpen_whip: Mapped[float] = mapped_column(Float, nullable=False)
    bullpen_k9: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bullpen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class MlbTeamBattingStat(Base):
    """MLB 팀 타선 집계 스탯 (FanGraphs 팀 타격 리더보드 기반)"""
    __tablename__ = "mlb_team_batting_stats"
    __table_args__ = (UniqueConstraint("season", "team_short", name="uq_mlb_team_batting"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    team_short: Mapped[str] = mapped_column(String(10), nullable=False)
    ops: Mapped[float] = mapped_column(Float, nullable=False)
    wrc_plus: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    k_rate: Mapped[float] = mapped_column(Float, nullable=False)
    bb_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    iso: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # Isolated Power (SLG-AVG)
    babip: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class MlbTeamBattingSplitStat(Base):
    """MLB 팀 타선 좌완/우완 투수 상대 OPS 스플릿
    실측 데이터가 없으면 팀 OPS 기반 보정값 저장 (source 컬럼으로 구분)
    split: 'vs_lhp' or 'vs_rhp'
    source: 'statcast' (실측) or 'estimated' (보정)
    """
    __tablename__ = "mlb_team_batting_split_stats"
    __table_args__ = (UniqueConstraint("season", "team_short", "split", name="uq_mlb_team_batting_split"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    team_short: Mapped[str] = mapped_column(String(10), nullable=False)
    split: Mapped[str] = mapped_column(String(10), nullable=False)    # "vs_lhp" or "vs_rhp"
    ops: Mapped[float] = mapped_column(Float, nullable=False)
    wrc_plus: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pa: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="estimated")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
