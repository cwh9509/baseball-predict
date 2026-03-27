"""
캐시 클라이언트
Redis가 있으면 Redis 사용, 없으면 메모리 딕셔너리로 자동 대체
개발 환경에서 Redis 없이도 정상 동작
"""
import json
import logging
import time
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# ── 메모리 캐시 폴백 ─────────────────────────────────
# Redis 연결 실패 시 사용하는 단순 딕셔너리 캐시
# {key: (value_json, expire_at_timestamp)}
_mem_cache: dict[str, tuple[str, float]] = {}

_redis_available: bool | None = None  # None=미확인, True/False=확인됨


async def _get_redis_client():
    """Redis 클라이언트 반환. URL 없거나 실패하면 None."""
    global _redis_available
    # URL이 비어있으면 바로 메모리 캐시 사용
    if not settings.redis_url:
        _redis_available = False
        return None
    if _redis_available is False:
        return None
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
        )
        await client.ping()
        if _redis_available is None:
            logger.info("Redis 연결 성공")
        _redis_available = True
        return client
    except Exception:
        if _redis_available is not False:
            logger.warning("Redis 없음 — 메모리 캐시로 대체")
        _redis_available = False
        return None


def get_redis():
    """FastAPI 의존성 주입용 (Redis 없으면 None)"""
    return None  # 비동기 흐름에서는 _get_redis_client() 직접 사용


async def cache_get(key: str) -> Any | None:
    """캐시에서 JSON 값 조회. 없으면 None 반환."""
    client = await _get_redis_client()
    if client:
        value = await client.get(key)
        await client.aclose()
        return json.loads(value) if value else None

    # 메모리 캐시 폴백
    entry = _mem_cache.get(key)
    if entry is None:
        return None
    value_json, expire_at = entry
    if time.time() > expire_at:
        del _mem_cache[key]
        return None
    return json.loads(value_json)


async def cache_set(key: str, value: Any, ttl: int) -> None:
    """JSON 직렬화 후 캐시에 저장."""
    serialized = json.dumps(value, ensure_ascii=False, default=str)

    client = await _get_redis_client()
    if client:
        await client.setex(key, ttl, serialized)
        await client.aclose()
        return

    # 메모리 캐시 폴백
    _mem_cache[key] = (serialized, time.time() + ttl)
    # 메모리 캐시 크기 제한 (1000개 초과 시 오래된 것 제거)
    if len(_mem_cache) > 1000:
        oldest = sorted(_mem_cache.items(), key=lambda x: x[1][1])[:200]
        for k, _ in oldest:
            _mem_cache.pop(k, None)


async def cache_delete(key: str) -> None:
    """캐시 키 삭제."""
    client = await _get_redis_client()
    if client:
        await client.delete(key)
        await client.aclose()
        return
    _mem_cache.pop(key, None)
