import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prism.config import settings
from prism.core.redis_client import redis_client
from prism.db.models import PromptCache


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
    value = await redis_client.get(f"cache:exact:{key}")
    return str(value) if value is not None else None


async def set_exact(key: str, response: str, ttl_s: int = 3600) -> None:
    await redis_client.set(f"cache:exact:{key}", response, ex=ttl_s)


async def embed(text: str) -> list[float]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{settings.ollama_base_url}/api/embeddings",
            json={"model": "nomic-embed-text", "prompt": text},
        )
        resp.raise_for_status()
    data: dict[str, object] = resp.json()
    embedding = data["embedding"]
    assert isinstance(embedding, list)
    return [float(v) for v in embedding]


def _prompt_text(messages: list[dict[str, str]]) -> str:
    return " ".join(m.get("content", "") for m in messages)


async def get_semantic(
    model: str,
    messages: list[dict[str, str]],
    db: AsyncSession,
    threshold: float = 0.95,
) -> str | None:
    vector = await embed(_prompt_text(messages))
    now = datetime.now(UTC)

    result = await db.execute(
        select(PromptCache)
        .where(PromptCache.virtual_model == model, PromptCache.expires_at > now)
        .order_by(PromptCache.prompt_embedding.cosine_distance(vector))
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None

    from pgvector.sqlalchemy import Vector as _Vec  # noqa: F401

    raw_emb: list[float] = list(row.prompt_embedding)
    dot = sum(a * b for a, b in zip(raw_emb, vector))
    mag_a = sum(x * x for x in raw_emb) ** 0.5
    mag_b = sum(x * x for x in vector) ** 0.5
    similarity = dot / (mag_a * mag_b) if mag_a and mag_b else 0.0
    return row.response_text if similarity >= threshold else None


async def store_semantic(
    model: str,
    messages: list[dict[str, str]],
    response_text: str,
    db: AsyncSession,
    ttl_hours: int = 24,
) -> None:
    vector = await embed(_prompt_text(messages))
    expires = datetime.now(UTC) + timedelta(hours=ttl_hours)
    entry = PromptCache(
        virtual_model=model,
        prompt_text=_prompt_text(messages),
        prompt_embedding=vector,
        response_text=response_text,
        expires_at=expires,
    )
    db.add(entry)
    await db.commit()
