import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException

from prism.config import settings

router = APIRouter(tags=["operational"])


@router.get("/healthz")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readiness() -> dict[str, str]:
    errors: list[str] = []

    try:
        conn = await asyncpg.connect(settings.database_url)
        await conn.fetchval("SELECT 1")
        await conn.close()
    except Exception as exc:
        errors.append(f"postgres: {exc}")

    try:
        client = aioredis.from_url(settings.redis_url)
        await client.ping()
        await client.aclose()
    except Exception as exc:
        errors.append(f"redis: {exc}")

    if errors:
        raise HTTPException(status_code=503, detail={"errors": errors})

    return {"status": "ready", "postgres": "ok", "redis": "ok"}
