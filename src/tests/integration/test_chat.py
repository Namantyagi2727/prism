import pytest
from httpx import ASGITransport, AsyncClient
from prism.db.models import RequestLog
from prism.main import app
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ADMIN_HEADERS = {"Authorization": "Bearer change-me-in-production"}


@pytest.fixture
async def api_key(db: AsyncSession) -> str:
    """Create a team + key and return the raw API key."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        team = await client.post(
            "/admin/teams", json={"name": "chat-test"}, headers=ADMIN_HEADERS
        )
        key_resp = await client.post(
            "/admin/keys",
            json={"team_id": team.json()["id"]},
            headers=ADMIN_HEADERS,
        )
    return str(key_resp.json()["key"])


@pytest.mark.integration
async def test_chat_completions_returns_openai_shape(
    api_key: str, db: AsyncSession
) -> None:
    # Requires: docker-compose up -d postgres redis  AND  ollama serve
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "fast",
                "messages": [
                    {"role": "user", "content": "Reply with just the word PONG"}
                ],
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )

    assert response.status_code == 200
    data = response.json()

    assert "choices" in data
    assert "usage" in data
    assert data["usage"]["prompt_tokens"] > 0

    meta = data["prism_metadata"]
    assert meta["provider_used"] == "ollama"
    assert meta["cache_hit"] is False
    assert meta["latency_ms"] > 0


@pytest.mark.integration
async def test_chat_logs_request(api_key: str, db: AsyncSession) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.post(
            "/v1/chat/completions",
            json={
                "model": "fast",
                "messages": [{"role": "user", "content": "Say hi"}],
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )

    result = await db.execute(
        select(RequestLog).order_by(RequestLog.created_at.desc()).limit(1)
    )
    log = result.scalar_one_or_none()
    assert log is not None
    assert log.provider_used == "ollama"
    assert log.status_code == 200
    assert log.prompt_tokens is not None and log.prompt_tokens > 0


@pytest.mark.integration
async def test_chat_rejects_invalid_key() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "fast", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer prism_invalid_key"},
        )
    assert response.status_code == 401
