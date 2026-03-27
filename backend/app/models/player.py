from sqlalchemy import Boolean, CHAR, CheckConstraint, Column, Date, ForeignKey, Integer, String, TIMESTAMP, text
from sqlalchemy.orm import relationship
from app.core.database import Base


class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"))
    league = Column(String(10), nullable=False)
    name = Column(String(150), nullable=False)
    position = Column(String(10), nullable=False)
    bats = Column(CHAR(1))
    throws = Column(CHAR(1))
    birth_date = Column(Date)
    external_id = Column(String(50))     # pybaseball playerid / statiz id
    is_active = Column(Boolean, server_default="true", nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"), nullable=False)

    team = relationship("Team", foreign_keys=[team_id])

    __table_args__ = (
        CheckConstraint("bats IN ('L','R','S')", name="chk_players_bats"),
        CheckConstraint("throws IN ('L','R')", name="chk_players_throws"),
    )
