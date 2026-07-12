import pytest
from httpx import ASGITransport, AsyncClient
from prism.main import app


async def test_liveness_returns_ok() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_503_when_postgres_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncpg

    async def _fail(*args: object, **kwargs: object) -> None:
        raise ConnectionRefusedError("postgres unreachable")

    monkeypatch.setattr(asyncpg, "connect", _fail)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/readyz")

    assert response.status_code == 503
    errors = response.json()["detail"]["errors"]
    assert any("postgres" in e for e in errors)


@pytest.mark.integration
async def test_readyz_returns_ready_when_deps_up() -> None:
    # Run first: docker-compose up -d postgres redis
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/readyz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["postgres"] == "ok"
    assert data["redis"] == "ok"
