import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prism.db.models import ApiKey, Team
from prism.main import app

ADMIN_HEADERS = {"Authorization": "Bearer change-me-in-production"}


@pytest.mark.integration
async def test_create_team(db: AsyncSession) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/admin/teams",
            json={"name": "acme", "monthly_budget_usd": 100.0},
            headers=ADMIN_HEADERS,
        )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "acme"
    assert "id" in data

    team_id = uuid.UUID(data["id"])
    result = await db.execute(select(Team).where(Team.id == team_id))
    assert result.scalar_one_or_none() is not None


@pytest.mark.integration
async def test_create_key(db: AsyncSession) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        team_resp = await client.post(
            "/admin/teams",
            json={"name": "key-test-team"},
            headers=ADMIN_HEADERS,
        )
        team_id = team_resp.json()["id"]

        key_resp = await client.post(
            "/admin/keys",
            json={"team_id": team_id, "rate_limit_rpm": 30},
            headers=ADMIN_HEADERS,
        )
    assert key_resp.status_code == 201
    data = key_resp.json()
    assert data["key"].startswith("prism_")
    assert "key_prefix" in data

    result = await db.execute(
        select(ApiKey).where(ApiKey.key_prefix == data["key_prefix"])
    )
    db_key = result.scalar_one_or_none()
    assert db_key is not None
    assert db_key.key_hash != data["key"]  # hash != raw key


@pytest.mark.integration
async def test_revoke_key(db: AsyncSession) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        team_resp = await client.post(
            "/admin/teams", json={"name": "revoke-team"}, headers=ADMIN_HEADERS
        )
        team_id = team_resp.json()["id"]
        key_resp = await client.post(
            "/admin/keys", json={"team_id": team_id}, headers=ADMIN_HEADERS
        )
        key_id = key_resp.json()["id"]

        revoke_resp = await client.delete(
            f"/admin/keys/{key_id}", headers=ADMIN_HEADERS
        )
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["revoked"] is True

    result = await db.execute(select(ApiKey).where(ApiKey.id == uuid.UUID(key_id)))
    db_key = result.scalar_one()
    assert db_key.is_active is False


@pytest.mark.integration
async def test_admin_auth_rejects_wrong_secret() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/admin/teams",
            json={"name": "x"},
            headers={"Authorization": "Bearer wrong-secret"},
        )
    assert response.status_code == 401
