import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from prism.main import app

ADMIN_HEADERS = {"Authorization": "Bearer change-me-in-production"}


@pytest.fixture
async def api_key(db: AsyncSession) -> str:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        team = await client.post(
            "/admin/teams",
            json={"name": "metrics-test"},
            headers=ADMIN_HEADERS,
        )
        key_resp = await client.post(
            "/admin/keys",
            json={"team_id": team.json()["id"]},
            headers=ADMIN_HEADERS,
        )
    return str(key_resp.json()["key"])


@pytest.mark.integration
async def test_metrics_endpoint_exposes_custom_metrics() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=True
    ) as client:
        resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert b"prism_requests_total" in resp.content
    assert b"prism_request_latency_seconds" in resp.content
    assert b"prism_guardrail_blocks_total" in resp.content


@pytest.mark.integration
async def test_guardrail_block_increments_counter(api_key: str) -> None:
    from prometheus_client import REGISTRY

    before = (
        REGISTRY.get_sample_value(
            "prism_guardrail_blocks_total", {"reason": "pii_detected"}
        )
        or 0.0
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "fast",
                "messages": [
                    {
                        "role": "user",
                        "content": "My email is test@example.com, help me.",
                    }
                ],
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
    assert resp.status_code == 400
    after = (
        REGISTRY.get_sample_value(
            "prism_guardrail_blocks_total", {"reason": "pii_detected"}
        )
        or 0.0
    )
    assert after > before


@pytest.mark.integration
async def test_cache_miss_then_hit_records_metrics(api_key: str) -> None:
    from prometheus_client import REGISTRY

    unique_id = uuid.uuid4().hex
    payload = {
        "model": "fast",
        "messages": [
            {"role": "user", "content": f"What is 7 times 8? run={unique_id}"}
        ],
        "temperature": 0.0,
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    hits_before = (
        REGISTRY.get_sample_value("prism_cache_hits_total", {"virtual_model": "fast"})
        or 0.0
    )
    misses_before = (
        REGISTRY.get_sample_value("prism_cache_misses_total", {"virtual_model": "fast"})
        or 0.0
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post("/v1/chat/completions", json=payload, headers=headers)
        second = await client.post(
            "/v1/chat/completions", json=payload, headers=headers
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["prism_metadata"]["cache_hit"] is True

    hits_after = (
        REGISTRY.get_sample_value("prism_cache_hits_total", {"virtual_model": "fast"})
        or 0.0
    )
    misses_after = (
        REGISTRY.get_sample_value("prism_cache_misses_total", {"virtual_model": "fast"})
        or 0.0
    )
    assert hits_after > hits_before
    assert misses_after > misses_before
