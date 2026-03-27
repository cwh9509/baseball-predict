"""
FastAPI 의존성 주입 모음
라우터에서 Depends(get_db), Depends(get_redis_client) 형태로 사용
"""
from typing import AsyncGenerator

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.redis_client import get_redis


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_redis_client() -> Redis:
    return get_redis()
