from sqlalchemy import Boolean, CheckConstraint, Column, Float, ForeignKey, Integer, Numeric, String, Text, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.core.database import Base


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    model_version = Column(String(50), nullable=False)
    predicted_winner_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    home_win_prob = Column(Numeric(5, 4), nullable=False)   # 0.0000 ~ 1.0000
    confidence_tier = Column(String(10), server_default="medium", nullable=False)
    # 예측 시점의 피처 값 스냅샷 (JSONB)
    feature_snapshot = Column(JSONB, server_default="{}", nullable=False)
    # LLM 해설
    llm_explanation = Column(Text)
    llm_model = Column(String(50))
    llm_generated_at = Column(TIMESTAMP(timezone=True))
    # 스코어 예측
    predicted_home_score = Column(Float, nullable=True)
    predicted_away_score = Column(Float, nullable=True)
    # 결과 추적
    was_correct = Column(Boolean)
    predicted_at = Column(TIMESTAMP(timezone=True), server_default=text("NOW()"), nullable=False)

    game = relationship("Game", foreign_keys=[game_id])
    predicted_winner = relationship("Team", foreign_keys=[predicted_winner_id])

    __table_args__ = (
        CheckConstraint("home_win_prob BETWEEN 0 AND 1", name="chk_predictions_prob"),
        CheckConstraint("confidence_tier IN ('low','medium','high')", name="chk_predictions_tier"),
    )
