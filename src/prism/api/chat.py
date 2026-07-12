import time
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prism.core.auth import validate_api_key
from prism.core.cost import calculate_cost
from prism.core.router import PROVIDERS, route
from prism.db.models import ApiKey, ModelRoute, RequestLog
from prism.db.session import get_db

router = APIRouter(tags=["gateway"])


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    temperature: float = 0.7
    stream: bool = False


@router.post("/v1/chat/completions")
async def chat_completions(
    body: ChatRequest,
    api_key: ApiKey = Depends(validate_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    if body.stream:
        raise HTTPException(status_code=400, detail="Streaming not supported yet")

    start = time.perf_counter()

    rows = await db.execute(
        select(ModelRoute)
        .where(ModelRoute.virtual_model == body.model)
        .order_by(ModelRoute.priority)
    )
    routes = [(r.provider, r.real_model, r.priority) for r in rows.scalars().all()]

    if not routes:
        raise HTTPException(
            status_code=404,
            detail=f"No routes configured for model '{body.model}'",
        )

    chat_result, provider_name, real_model, fallback_triggered = await route(
        routes=routes,
        providers=PROVIDERS,
        messages=[m.model_dump() for m in body.messages],
        temperature=body.temperature,
    )

    latency_ms = int((time.perf_counter() - start) * 1000)
    cost: Decimal = calculate_cost(
        provider_name,
        real_model,
        chat_result.prompt_tokens,
        chat_result.completion_tokens,
    )

    log = RequestLog(
        api_key_id=api_key.id,
        virtual_model=body.model,
        provider_used=provider_name,
        fallback_triggered=fallback_triggered,
        prompt_tokens=chat_result.prompt_tokens,
        completion_tokens=chat_result.completion_tokens,
        cost_usd=cost,
        latency_ms=latency_ms,
        status_code=200,
    )
    db.add(log)
    await db.commit()

    return {
        **chat_result.raw,
        "prism_metadata": {
            "provider_used": provider_name,
            "cache_hit": False,
            "fallback_triggered": fallback_triggered,
            "cost_usd": float(cost),
            "latency_ms": latency_ms,
        },
    }
