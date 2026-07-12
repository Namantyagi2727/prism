# Phase 0 — Project Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bootstrap the Prism repository with a working FastAPI skeleton, Docker Compose environment (Postgres + Redis), health endpoints, pre-commit hooks, and a passing test suite — everything needed so Phase 1 can start coding features immediately.

**Architecture:** Bare FastAPI app with two operational endpoints (`/healthz` liveness, `/readyz` readiness). Config via pydantic-settings from environment variables. No business logic yet — just the skeleton that Phase 1 fills in.

**Tech Stack:** Python 3.12, FastAPI, pydantic-settings, asyncpg (direct ping only), redis-py async, pytest + httpx, Docker Compose, ruff, mypy, uv (package manager)

## Global Constraints

- Python >= 3.12 strictly
- Use `uv` as the package/venv manager throughout
- `src` layout: all application code under `src/prism/`, all tests under `src/tests/`
- No secrets committed — `.env` is gitignored, `.env.example` is committed
- Every task ends with a `git commit`
- User pushes to GitHub manually — plans only provide `git add` / `git commit` commands, never `git push`
- All test files use type annotations; all source files pass `mypy --strict`
- `asyncio_mode = "auto"` in pytest — no `@pytest.mark.asyncio` needed on individual tests

---

## File Map

| File | Purpose |
|---|---|
| `pyproject.toml` | Project metadata, dependencies, ruff/mypy/pytest config |
| `.gitignore` | Exclude `.env`, `__pycache__`, `.venv`, etc. |
| `.env.example` | Template — safe to commit, no real values |
| `src/prism/__init__.py` | Empty — marks package root |
| `src/prism/config.py` | `Settings` class via pydantic-settings; exposes `database_url` and `sqlalchemy_url` properties |
| `src/prism/main.py` | FastAPI app instantiation; mounts routers |
| `src/prism/api/__init__.py` | Empty |
| `src/prism/api/health.py` | `/healthz` and `/readyz` route handlers |
| `src/tests/__init__.py` | Empty |
| `src/tests/conftest.py` | Registers `integration` pytest marker |
| `src/tests/test_config.py` | Unit tests for Settings defaults and URL properties |
| `src/tests/test_health.py` | Unit + integration tests for health endpoints |
| `deploy/docker/Dockerfile` | Single-stage Python 3.12-slim image (multi-stage optimization deferred to Phase 6) |
| `docker-compose.yml` | Postgres (pgvector image) + Redis + app service |
| `.pre-commit-config.yaml` | ruff lint + ruff format hooks |

---

## Task 1: Git init, directory structure, and pyproject.toml

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/prism/__init__.py`
- Create: `src/prism/api/__init__.py`
- Create: `src/tests/__init__.py`

**Interfaces:**
- Produces: installable `prism` package; `uv pip install -e ".[dev]"` succeeds

---

- [ ] **Step 1: Install uv if not already present**

```bash
brew install uv
```

Expected: `uv --version` prints a version string.

- [ ] **Step 2: Create the directory skeleton**

Your working directory is already `/Users/naman/Developer/LLM Gateway/` — this IS the project root. Run from there:

```bash
mkdir -p src/prism/api
mkdir -p src/tests
mkdir -p deploy/docker
```

The `docs/` directory already exists (the spec lives there). All subsequent steps assume your working directory is `/Users/naman/Developer/LLM Gateway/`.

- [ ] **Step 3: Initialize git**

```bash
git init
git branch -M main
```

- [ ] **Step 4: Write pyproject.toml**

```toml
[project]
name = "prism"
version = "0.1.0"
description = "Production LLM gateway with routing, caching, guardrails, and observability"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic-settings>=2.3.0",
    "asyncpg>=0.29.0",
    "redis>=5.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2.0",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.27.0",
    "ruff>=0.4.9",
    "mypy>=1.10.0",
    "pre-commit>=3.7.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/prism"]

[tool.ruff]
line-length = 88
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]

[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["src/tests"]
markers = ["integration: requires docker-compose services running (postgres + redis)"]
```

- [ ] **Step 5: Write .gitignore**

```
# Python
__pycache__/
*.py[cod]
.venv/
*.egg-info/
dist/
.eggs/

# Environment — never commit real values
.env

# Test artifacts
.pytest_cache/
.coverage
htmlcov/

# Type checker
.mypy_cache/

# Linter
.ruff_cache/

# Editors
.vscode/
.idea/
*.swp

# Docker
*.log
```

- [ ] **Step 6: Write .env.example**

```
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=prism
POSTGRES_PASSWORD=prism
POSTGRES_DB=prism
REDIS_URL=redis://localhost:6379
LOG_LEVEL=INFO
```

- [ ] **Step 7: Copy .env.example to .env (your local only — gitignored)**

```bash
cp .env.example .env
```

- [ ] **Step 8: Create empty package init files**

`src/prism/__init__.py` — empty file  
`src/prism/api/__init__.py` — empty file  
`src/tests/__init__.py` — empty file

- [ ] **Step 9: Create virtual environment and install dependencies**

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

- [ ] **Step 10: Verify the package is importable**

```bash
python -c "import prism; print('ok')"
```

Expected output: `ok`

- [ ] **Step 11: Commit**

```bash
git add pyproject.toml .gitignore .env.example src/
git commit -m "feat: Phase 0 — repo scaffold, package structure, dependencies"
```

---

## Task 2: Config module

**Files:**
- Create: `src/prism/config.py`
- Create: `src/tests/test_config.py`

**Interfaces:**
- Produces:
  - `from prism.config import settings` — singleton `Settings` instance
  - `settings.database_url` → `str` — `postgresql://user:pass@host:port/db` (for asyncpg direct calls)
  - `settings.sqlalchemy_url` → `str` — `postgresql+asyncpg://user:pass@host:port/db` (for SQLAlchemy in Phase 1)

---

- [ ] **Step 1: Write the failing test**

`src/tests/test_config.py`:

```python
from prism.config import settings


def test_postgres_defaults() -> None:
    assert settings.postgres_host == "localhost"
    assert settings.postgres_port == 5432
    assert settings.postgres_user == "prism"
    assert settings.postgres_db == "prism"


def test_database_url_format() -> None:
    url = settings.database_url
    assert url.startswith("postgresql://")
    assert "localhost" in url
    assert "/prism" in url


def test_sqlalchemy_url_format() -> None:
    url = settings.sqlalchemy_url
    assert url.startswith("postgresql+asyncpg://")
    assert "localhost" in url


def test_redis_url_default() -> None:
    assert settings.redis_url == "redis://localhost:6379"
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest src/tests/test_config.py -v
```

Expected: `ImportError` — `prism.config` does not exist yet.

- [ ] **Step 3: Write src/prism/config.py**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "prism"
    postgres_password: str = "prism"
    postgres_db: str = "prism"
    redis_url: str = "redis://localhost:6379"
    log_level: str = "INFO"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sqlalchemy_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest src/tests/test_config.py -v
```

Expected: 4 tests PASSED.

- [ ] **Step 5: Type-check**

```bash
mypy src/prism/config.py
```

Expected: `Success: no issues found in 1 source file`

- [ ] **Step 6: Commit**

```bash
git add src/prism/config.py src/tests/test_config.py
git commit -m "feat: add Settings config module with postgres and redis URL properties"
```

---

## Task 3: FastAPI app skeleton and health endpoints

**Files:**
- Create: `src/prism/main.py`
- Create: `src/prism/api/health.py`
- Create: `src/tests/conftest.py`
- Create: `src/tests/test_health.py`

**Interfaces:**
- Consumes: `settings.database_url` (str), `settings.redis_url` (str)
- Produces:
  - `GET /healthz` → `200 {"status": "ok"}` (no deps, always fast)
  - `GET /readyz` → `200 {"status": "ready", "postgres": "ok", "redis": "ok"}` when both up; `503 {"detail": {"errors": [...]}}` when either down
  - `app` FastAPI instance importable from `prism.main`

---

- [ ] **Step 1: Write conftest.py to register the integration marker**

`src/tests/conftest.py`:

```python
import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: requires docker-compose services running (postgres + redis)",
    )
```

- [ ] **Step 2: Write the failing tests**

`src/tests/test_health.py`:

```python
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
```

- [ ] **Step 3: Run to verify they fail**

```bash
pytest src/tests/test_health.py -v -m "not integration"
```

Expected: `ImportError` — `prism.main` does not exist yet.

- [ ] **Step 4: Write src/prism/api/health.py**

```python
from fastapi import APIRouter, HTTPException

import asyncpg
import redis.asyncio as aioredis

from prism.config import settings

router = APIRouter(tags=["operational"])


@router.get("/healthz")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readiness() -> dict[str, str]:
    errors: list[str] = []

    try:
        conn = await asyncpg.connect(settings.database_url)
        await conn.fetchval("SELECT 1")
        await conn.close()
    except Exception as exc:
        errors.append(f"postgres: {exc}")

    try:
        client = aioredis.from_url(settings.redis_url)
        await client.ping()
        await client.aclose()
    except Exception as exc:
        errors.append(f"redis: {exc}")

    if errors:
        raise HTTPException(status_code=503, detail={"errors": errors})

    return {"status": "ready", "postgres": "ok", "redis": "ok"}
```

- [ ] **Step 5: Write src/prism/main.py**

```python
from fastapi import FastAPI

from prism.api.health import router as health_router

app = FastAPI(title="Prism LLM Gateway", version="0.1.0")

app.include_router(health_router)
```

- [ ] **Step 6: Run unit tests (no containers needed)**

```bash
pytest src/tests/test_health.py -v -m "not integration"
```

Expected: 2 tests PASSED (`test_liveness_returns_ok`, `test_readyz_503_when_postgres_unreachable`).

- [ ] **Step 7: Type-check both new files**

```bash
mypy src/prism/api/health.py src/prism/main.py
```

Expected: `Success: no issues found in 2 source files`

- [ ] **Step 8: Commit**

```bash
git add src/prism/main.py src/prism/api/health.py src/tests/conftest.py src/tests/test_health.py
git commit -m "feat: add FastAPI app skeleton with /healthz and /readyz endpoints"
```

---

## Task 4: Docker Compose and Dockerfile

**Files:**
- Create: `deploy/docker/Dockerfile`
- Create: `docker-compose.yml`

**Interfaces:**
- Consumes: `prism.main:app` (the FastAPI app)
- Produces: `docker-compose up` brings up Postgres, Redis, and the Prism app; all three health endpoints respond correctly

---

- [ ] **Step 1: Write deploy/docker/Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
COPY src ./src

RUN uv pip install --system --no-cache .

EXPOSE 8000

CMD ["uvicorn", "prism.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Write docker-compose.yml**

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: prism
      POSTGRES_PASSWORD: prism
      POSTGRES_DB: prism
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U prism"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  app:
    build:
      context: .
      dockerfile: deploy/docker/Dockerfile
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      POSTGRES_HOST: postgres
      REDIS_URL: redis://redis:6379
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

volumes:
  postgres_data:
```

Note: the `environment` block in `app` overrides `POSTGRES_HOST` and `REDIS_URL` from `.env` so the app connects to the correct container hostnames inside the Docker network. Your local `.env` keeps `localhost` for running uvicorn directly outside Docker.

- [ ] **Step 3: Start only the dependency services first (for local dev workflow)**

```bash
docker-compose up -d postgres redis
```

Wait ~10 seconds for containers to be healthy, then:

```bash
docker-compose ps
```

Expected: both `postgres` and `redis` show `healthy`.

- [ ] **Step 4: Run the integration test against live containers**

```bash
pytest src/tests/test_health.py -v -m integration
```

Expected: `test_readyz_returns_ready_when_deps_up` PASSED.

- [ ] **Step 5: Build and start the full stack**

```bash
docker-compose up --build
```

In a separate terminal:

```bash
curl http://localhost:8000/healthz
# Expected: {"status":"ok"}

curl http://localhost:8000/readyz
# Expected: {"status":"ready","postgres":"ok","redis":"ok"}
```

- [ ] **Step 6: Stop everything**

```bash
docker-compose down
```

- [ ] **Step 7: Commit**

```bash
git add deploy/docker/Dockerfile docker-compose.yml
git commit -m "feat: add Dockerfile and docker-compose with Postgres, Redis, and app services"
```

---

## Task 5: Pre-commit hooks

**Files:**
- Create: `.pre-commit-config.yaml`

**Interfaces:**
- Produces: `git commit` automatically runs ruff lint and ruff format; failing lint blocks the commit

---

- [ ] **Step 1: Write .pre-commit-config.yaml**

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.9
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

- [ ] **Step 2: Install the hooks**

```bash
pre-commit install
```

Expected: `pre-commit installed at .git/hooks/pre-commit`

- [ ] **Step 3: Run against all existing files to verify clean**

```bash
pre-commit run --all-files
```

Expected: all hooks pass. If ruff auto-fixes anything, the files will be modified — just `git add` the changes and re-run.

- [ ] **Step 4: Run the full test suite one final time to confirm nothing is broken**

```bash
pytest src/tests/ -v -m "not integration"
```

Expected: all unit tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add .pre-commit-config.yaml
git commit -m "chore: add pre-commit hooks for ruff lint and format"
```

---

## Phase 0 Complete — GitHub Push Commands

At this point, create a new GitHub repo named `prism` (do this on github.com — set it to public, no README, no .gitignore since we have our own). Then run:

```bash
git remote add origin https://github.com/<your-username>/prism.git
git push -u origin main
```

**Demo gate:** `docker-compose up --build` → `curl http://localhost:8000/healthz` returns `{"status":"ok"}` and `curl http://localhost:8000/readyz` returns `{"status":"ready","postgres":"ok","redis":"ok"}`.

**Next:** Phase 1 plan — Ollama provider, `/v1/chat/completions` passthrough, API key auth, Alembic migrations, request logging.
