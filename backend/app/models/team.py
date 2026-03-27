from sqlalchemy import CheckConstraint, Column, Integer, Numeric, String, TIMESTAMP, text
from app.core.database import Base


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)
    league = Column(String(10), nullable=False)
    name = Column(String(100), nullable=False)
    short_name = Column(String(20), nullable=False)
    city = Column(String(100))
    stadium_name = Column(String(150))
    stadium_lat = Column(Numeric(9, 6))
    stadium_lon = Column(Numeric(9, 6))
    park_factor = Column(Numeric(5, 3), server_default="1.000")
    surface = Column(String(20), server_default="grass", nullable=False)
    roof_type = Column(String(20), server_default="open", nullable=False)
    capacity = Column(Integer)
    created_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"), nullable=False)

    __table_args__ = (
        CheckConstraint("league IN ('KBO', 'MLB', 'NPB')", name="chk_teams_league"),
        CheckConstraint("surface IN ('grass', 'turf', 'hybrid')", name="chk_teams_surface"),
        CheckConstraint("roof_type IN ('open', 'retractable', 'dome')", name="chk_teams_roof"),
    )
