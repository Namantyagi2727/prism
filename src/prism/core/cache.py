import hashlib
import json

import redis.asyncio as aioredis

from prism.config import settings


def exact_cache_key(
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
) -> str:
    payload = json.dumps(
        {"model": model, "messages": messages, "temperature": temperature},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


async def get_exact(key: str) -> str | None:
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        value = await r.get(f"cache:exact:{key}")
        return str(value) if value is not None else None
    finally:
        await r.aclose()


async def set_exact(key: str, response: str, ttl_s: int = 3600) -> None:
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await r.set(f"cache:exact:{key}", response, ex=ttl_s)
    finally:
        await r.aclose()
