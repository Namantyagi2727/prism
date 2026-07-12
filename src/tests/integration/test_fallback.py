import pytest
from httpx import ASGITransport, AsyncClient
from prism.db.models import RequestLog
from prism.main import app
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ADMIN_HEADERS = {"Authorization": "Bearer change-me-in-production"}


@pytest.fixture
async def api_key(db: AsyncSession) -> str:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        team = await client.post(
            "/admin/teams",
            json={"name": "fallback-test"},
            headers=ADMIN_HEADERS,
        )
        key_resp = await client.post(
            "/admin/keys",
            json={"team_id": team.json()["id"]},
            headers=ADMIN_HEADERS,
        )
    return str(key_resp.json()["key"])


@pytest.mark.integration
async def test_fallback_when_ollama_fails(
    api_key: str, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force Ollama to fail; expect fallback to openai mock."""
    from prism.providers.base import ChatResult
    from prism.providers.ollama_provider import OllamaProvider

    async def _fail(
        self: OllamaProvider,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: object,
    ) -> ChatResult:
        raise RuntimeError("simulated Ollama failure")

    monkeypatch.setattr(OllamaProvider, "chat", _fail)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "fast",
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["prism_metadata"]["provider_used"] == "openai"
    assert data["prism_metadata"]["fallback_triggered"] is True

    result = await db.execute(
        select(RequestLog).order_by(RequestLog.created_at.desc()).limit(1)
    )
    log = result.scalar_one()
    assert log.provider_used == "openai"
    assert log.fallback_triggered is True


@pytest.mark.integration
async def test_normal_request_not_flagged_as_fallback(
    api_key: str, db: AsyncSession
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "fast",
                "messages": [{"role": "user", "content": "Say hi"}],
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )

    assert response.status_code == 200
    assert response.json()["prism_metadata"]["fallback_triggered"] is False
