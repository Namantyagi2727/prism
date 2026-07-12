import time
import uuid

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prism.config import settings
from prism.core.security import hash_key
from prism.db.models import ApiKey
from prism.db.session import get_db

_bearer = HTTPBearer()


def check_rate_limit_key(api_key_id: str, limit_rpm: int) -> str:
    minute = int(time.time() // 60)
    return f"rl:{api_key_id}:{minute}:{limit_rpm}"


async def _check_rate_limit(api_key_id: uuid.UUID, limit_rpm: int) -> bool:
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    key = f"rl:{api_key_id}:{int(time.time() // 60)}"
    try:
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, 60)
        return int(count) <= limit_rpm
    finally:
        await r.aclose()


async def validate_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    key_hash = hash_key(credentials.credentials)
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.key_hash == key_hash,
            ApiKey.is_active.is_(True),
        )
    )
    api_key = result.scalar_one_or_none()

    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    if not await _check_rate_limit(api_key.id, api_key.rate_limit_rpm):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    return api_key
