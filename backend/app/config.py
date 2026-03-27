"""
앱 전체 환경변수 관리
Pydantic Settings가 .env 파일을 자동으로 읽습니다.
"""
from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 안에 .env가 있으면 우선, 없으면 상위 디렉토리(프로젝트 루트) 확인
_here = Path(__file__).resolve().parent.parent  # backend/
_env_file = _here / ".env" if (_here / ".env").exists() else _here.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_env_file),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Database ---
    database_url: str = "postgresql+asyncpg://baseball:baseball@localhost:5432/baseball"

    # --- Redis (비어있으면 메모리 캐시로 자동 대체) ---
    redis_url: str = ""

    # --- Anthropic Claude API ---
    anthropic_api_key: str = ""

    # --- OpenWeatherMap API ---
    owm_api_key: str = ""

    # --- 앱 설정 ---
    league: Literal["KBO", "MLB", "NPB"] = "MLB"
    model_path: str = "/app/ml_models"
    scheduler_timezone: str = "America/New_York"
    log_level: str = "INFO"

    # --- statiz.co.kr 로그인 (KBO 투수 통계) ---
    statiz_id: str = ""
    statiz_pw: str = ""

    # --- LLM 비용 제어 ---
    llm_explanations_enabled: bool = True

    # --- Admin API (라인업 수동 업데이트 등) ---
    admin_api_key: str = ""   # 비어있으면 인증 생략

    # --- CORS ---
    allowed_origins: list[str] = ["http://localhost:3000", "http://frontend:3000"]


# 싱글톤 인스턴스 (앱 전체에서 import해서 사용)
settings = Settings()
