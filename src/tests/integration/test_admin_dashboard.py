import base64

import pytest
from httpx import ASGITransport, AsyncClient

from prism.main import app

ADMIN_SECRET = "change-me-in-production"


def _basic_auth_header(password: str, username: str = "admin") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.mark.integration
async def test_dashboard_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/admin/dashboard")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Basic"


@pytest.mark.integration
async def test_dashboard_rejects_wrong_password() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/admin/dashboard", headers=_basic_auth_header("wrong-secret")
        )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Basic"


@pytest.mark.integration
async def test_dashboard_renders_with_correct_credentials() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/admin/dashboard", headers=_basic_auth_header(ADMIN_SECRET)
        )
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'id="dashboard-data"' in response.text
