import json
import logging

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger("eve.cache")
_redis: Redis | None = None


def _client() -> Redis | None:
    global _redis
    if not settings.redis_url:
        return None
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1)
    return _redis


def get_cached_json(key: str):
    client = _client()
    if client is None:
        return None
    try:
        value = client.get(key)
        return json.loads(value) if value else None
    except (RedisError, ValueError):
        logger.warning("redis_cache_read_failed", extra={"event": "redis_cache_read_failed"})
        return None


def set_cached_json(key: str, value, ttl_seconds: int | None = None) -> None:
    client = _client()
    if client is None:
        return
    try:
        client.setex(key, ttl_seconds or settings.cache_ttl_seconds, json.dumps(value, separators=(",", ":")))
    except (RedisError, TypeError, ValueError):
        logger.warning("redis_cache_write_failed", extra={"event": "redis_cache_write_failed"})


def delete_cached_pattern(pattern: str) -> None:
    client = _client()
    if client is None:
        return
    try:
        keys = list(client.scan_iter(match=pattern, count=100))
        if keys:
            client.delete(*keys)
    except RedisError:
        logger.warning("redis_cache_invalidation_failed", extra={"event": "redis_cache_invalidation_failed"})
