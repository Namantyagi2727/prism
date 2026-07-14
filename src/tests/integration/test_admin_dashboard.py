import base64
import uuid

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


@pytest.mark.integration
async def test_dashboard_shows_seeded_team_and_guardrail_data() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        team = await client.post(
            "/admin/teams",
            json={"name": "dashboard-view-test"},
            headers={"Authorization": f"Bearer {ADMIN_SECRET}"},
        )
        team_id = team.json()["id"]
        key_resp = await client.post(
            "/admin/keys",
            json={"team_id": team_id},
            headers={"Authorization": f"Bearer {ADMIN_SECRET}"},
        )
        api_key = key_resp.json()["key"]

        await client.post(
            "/v1/chat/completions",
            json={
                "model": "fast",
                "messages": [
                    {"role": "user", "content": "My email is test@example.com"}
                ],
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )

        response = await client.get(
            "/admin/dashboard", headers=_basic_auth_header(ADMIN_SECRET)
        )

    assert response.status_code == 200
    assert "dashboard-view-test" in response.text
    assert 'role="tablist"' in response.text
    assert 'id="panel-overview"' in response.text
    assert 'id="panel-cost"' in response.text
    assert 'id="panel-performance"' in response.text
    assert 'id="panel-safety"' in response.text


@pytest.mark.integration
async def test_dashboard_includes_tab_and_chart_script() -> None:
    # Seed our own data so the chart <svg> elements are guaranteed to render
    # regardless of what other tests have (or haven't) inserted in the same
    # 24h window — the template swaps to an empty-state div when a series
    # has no rows, so this can't rely on shared session state.
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        team = await client.post(
            "/admin/teams",
            json={"name": "dashboard-script-test"},
            headers={"Authorization": f"Bearer {ADMIN_SECRET}"},
        )
        key_resp = await client.post(
            "/admin/keys",
            json={"team_id": team.json()["id"]},
            headers={"Authorization": f"Bearer {ADMIN_SECRET}"},
        )
        api_key = key_resp.json()["key"]

        # A shared, session-scoped Redis backs the exact cache, so a generic
        # "hi" here could get cache-served to (or collide with) an unrelated
        # test's request. Get uniqueness from `temperature` instead of the
        # message content — content goes through the guardrail's PII/NER
        # scan, and a random token embedded in short text has a real (not
        # astronomically small) chance of a false-positive PII match, which
        # made this exact pattern flaky elsewhere in the suite.
        unique_temperature = (uuid.uuid4().int % 1_000_000) / 1_000_000
        await client.post(
            "/v1/chat/completions",
            json={
                "model": "fast",
                "messages": [{"role": "user", "content": "Say hi"}],
                "temperature": unique_temperature,
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )

        response = await client.get(
            "/admin/dashboard", headers=_basic_auth_header(ADMIN_SECRET)
        )
    # Request Volume (line) and Provider Mix (bar) both depend only on
    # overview data, which the chat completion above guarantees is non-empty.
    assert 'data-chart="line"' in response.text
    assert 'data-chart="bar"' in response.text
    assert "activateTab" in response.text
