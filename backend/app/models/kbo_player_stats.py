"""KBO 선수 경기/시즌 스탯 (자체 DB 집계 — statiz는 초기 시드용)"""
from datetime import datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class KboPlayerGameStat(Base):
    """경기 종료 후 Naver 박스스코어에서 수집한 선수 1경기 기록"""
    __tablename__ = "kbo_player_game_stats"
    __table_args__ = (
        UniqueConstraint("game_id", "player_name", "role", name="uq_kbo_player_game"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    game_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    player_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    team_short: Mapped[str] = mapped_column(String(20), nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False)  # batter | pitcher
    is_starter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    opponent_sp_throws: Mapped[str] = mapped_column(String(2), nullable=True)  # L | R

    # 타격
    pa: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ab: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    doubles: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    triples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hr: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    so: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hbp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sf: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 투구
    ip: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    er: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hits_allowed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bb_allowed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    so_pitched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    source: Mapped[str] = mapped_column(String(20), nullable=False, default="naver")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class KboPlayerSeasonStat(Base):
    """시즌 누적 스탯 — statiz 시드 후 경기별 집계로 갱신"""
    __tablename__ = "kbo_player_season_stats"
    __table_args__ = (
        UniqueConstraint("season", "name", "team_short", "role", name="uq_kbo_player_season"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    team_short: Mapped[str] = mapped_column(String(20), nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False)  # batter | pitcher

    # 타격 누적
    pa: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ab: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    doubles: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    triples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hr: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    so: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hbp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sf: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ops: Mapped[float] = mapped_column(Float, nullable=True)
    k_rate: Mapped[float] = mapped_column(Float, nullable=True)

    # 투구 누적
    ip: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    er: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hits_allowed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bb_allowed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    so_pitched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    games_pitched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    era: Mapped[float] = mapped_column(Float, nullable=True)
    whip: Mapped[float] = mapped_column(Float, nullable=True)
    k9: Mapped[float] = mapped_column(Float, nullable=True)
    handedness: Mapped[str] = mapped_column(String(2), nullable=True)
    recent_era: Mapped[float] = mapped_column(Float, nullable=True)
    recent_whip: Mapped[float] = mapped_column(Float, nullable=True)

    # db 집계 샘플 수 (statiz 시드 대체 판단용)
    db_game_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # statiz | db | merged
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="statiz")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
