from sqlalchemy import Boolean, CheckConstraint, Column, Date, ForeignKey, Integer, SmallInteger, String, TIMESTAMP, Time, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True)
    league = Column(String(10), nullable=False)
    game_date = Column(Date, nullable=False)
    game_time = Column(Time(timezone=True))
    home_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    away_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    home_starter_id = Column(Integer, ForeignKey("players.id"))
    away_starter_id = Column(Integer, ForeignKey("players.id"))
    home_starter_name = Column(String(50))   # KBO/NPB 선발투수 이름 (직접 저장)
    away_starter_name = Column(String(50))
    venue = Column(String(150))
    status = Column(String(20), server_default="scheduled", nullable=False)
    # 경기 결과 (종료 후 채워짐)
    home_score = Column(SmallInteger)
    away_score = Column(SmallInteger)
    winner_team_id = Column(Integer, ForeignKey("teams.id"))
    innings_played = Column(SmallInteger)
    external_game_id = Column(String(50))   # MLB game_pk 또는 KBO 경기 코드

    # 라인업 (경기 시작 전 발표 시 채워짐)
    home_lineup_json = Column(JSONB)        # [{"order":1,"name":"...","position":"..."},...]
    away_lineup_json = Column(JSONB)
    lineup_locked = Column(Boolean, default=False)          # True = 공식 라인업 확정
    lineup_locked_at = Column(TIMESTAMP(timezone=True))

    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"), nullable=False)

    home_team = relationship("Team", foreign_keys=[home_team_id])
    away_team = relationship("Team", foreign_keys=[away_team_id])
    home_starter = relationship("Player", foreign_keys=[home_starter_id])
    away_starter = relationship("Player", foreign_keys=[away_starter_id])
    winner_team = relationship("Team", foreign_keys=[winner_team_id])

    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled','in_progress','final','postponed','cancelled')",
            name="chk_games_status",
        ),
    )
