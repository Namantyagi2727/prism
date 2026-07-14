import random
import uuid

import httpx
from locust import HttpUser, between, events, task
from locust.env import Environment

ADMIN_SECRET = "change-me-in-production"

SAFE_PROMPTS = [
    "What is the capital of France?",
    "What year did the Berlin Wall fall?",
    "Explain photosynthesis in one sentence.",
    "What is the boiling point of water in Celsius?",
    "Name three primary colors.",
    "What is the largest planet in the solar system?",
]

GUARDRAIL_PROMPT = "My email is test@example.com, please help me reset my password."

_state: dict[str, str] = {}


@events.test_start.add_listener
def on_test_start(environment: Environment, **kwargs: object) -> None:
    host = environment.host
    if not host:
        raise RuntimeError("Locust --host is required (e.g. http://localhost:8000)")

    client = httpx.Client(base_url=host, timeout=10.0)
    admin_headers = {"Authorization": f"Bearer {ADMIN_SECRET}"}

    team_resp = client.post(
        "/admin/teams",
        json={"name": f"loadtest-{uuid.uuid4().hex[:8]}"},
        headers=admin_headers,
    )
    team_resp.raise_for_status()
    team_id = team_resp.json()["id"]

    key_resp = client.post(
        "/admin/keys",
        json={"team_id": team_id, "rate_limit_rpm": 100000},
        headers=admin_headers,
    )
    key_resp.raise_for_status()
    _state["api_key"] = key_resp.json()["key"]


class PrismUser(HttpUser):
    abstract = True

    def _chat(
        self,
        content: str,
        model: str,
        temperature: float,
        name: str,
        expect_status: int = 200,
    ) -> None:
        with self.client.post(
            "/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "temperature": temperature,
            },
            headers={"Authorization": f"Bearer {_state['api_key']}"},
            name=name,
            catch_response=True,
        ) as response:
            if response.status_code == expect_status:
                # catch_response=True disables Locust's default 2xx-only
                # success check, so a non-2xx expect_status (the
                # guardrail-block task expects 400) must be marked
                # successful explicitly or it's reported as a failure.
                response.success()
            else:
                response.failure(
                    f"expected {expect_status}, got {response.status_code}: "
                    f"{response.text[:200]}"
                )


class GatewayOverheadUser(PrismUser):
    weight = 9
    wait_time = between(0.01, 0.1)

    @task(70)
    def cache_miss(self) -> None:
        prompt = random.choice(SAFE_PROMPTS)
        self._chat(
            prompt,
            model="mock-fast",
            temperature=random.random(),
            name="/v1/chat/completions [mock-fast cache-miss]",
        )

    @task(20)
    def cache_hit(self) -> None:
        self._chat(
            SAFE_PROMPTS[0],
            model="mock-fast",
            temperature=0.0,
            name="/v1/chat/completions [mock-fast cache-hit]",
        )

    @task(10)
    def guardrail_block(self) -> None:
        self._chat(
            GUARDRAIL_PROMPT,
            model="mock-fast",
            temperature=0.5,
            name="/v1/chat/completions [mock-fast guardrail-block]",
            expect_status=400,
        )
