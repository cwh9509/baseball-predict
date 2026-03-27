"""
SQLAlchemy 비동기 DB 엔진 및 세션 팩토리
asyncpg 드라이버 사용 (psycopg2 사용 금지 — 이벤트 루프 블로킹 발생)
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Neon 서버리스 환경에서는 커넥션 풀을 작게 유지 (idle 커넥션 자동 종료)
# 로컬 개발: pool_size=5, 배포: pool_size=2 (무료 티어 커넥션 수 제한)
_is_neon = "neon.tech" in settings.database_url

engine = create_async_engine(
    settings.database_url,
    echo=(settings.log_level == "DEBUG"),
    pool_size=2 if _is_neon else 5,
    max_overflow=3 if _is_neon else 10,
    pool_pre_ping=True,
    pool_recycle=300,     # 5분마다 커넥션 재생성 (Neon idle 타임아웃 대응)
    connect_args={"ssl": "require"} if _is_neon else {},
)

# 세션 팩토리
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # commit 후에도 객체 접근 가능
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    """모든 ORM 모델의 부모 클래스"""
    pass


async def get_db() -> AsyncSession:
    """FastAPI 의존성 주입용 DB 세션 제공자"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
