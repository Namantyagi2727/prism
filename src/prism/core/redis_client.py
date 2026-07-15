import redis.asyncio as aioredis

from prism.config import settings

redis_client: aioredis.Redis = aioredis.from_url(
    settings.redis_url, decode_responses=True
)
