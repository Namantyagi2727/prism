# Phase 1 — Core Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A real request enters Prism with an API key, gets validated, forwarded to Ollama, cost-calculated, and logged to Postgres — all verifiable end-to-end.

**Architecture:** Five layers added on top of the Phase 0 skeleton: (1) SQLAlchemy models + Alembic migrations for all four tables; (2) API key generation and admin endpoints to create teams/keys; (3) auth FastAPI dependency that validates keys and enforces Redis rate limits; (4) Ollama provider + cost calculator; (5) `/v1/chat/completions` endpoint that wires all layers together and logs every request.

**Tech Stack:** SQLAlchemy 2.0 async, Alembic, httpx (moved to main deps), asyncpg, redis-py async, Pydantic v2

## Global Constraints

- Python >= 3.12 strictly; `src` layout; `uv` for packages
- All source files pass `mypy --strict` with `sqlalchemy.ext.mypy.plugin`
- TDD: write failing test → implement → verify pass → commit
- Integration tests require: `docker-compose up -d postgres redis` + `ollama serve`
- Never store raw API keys — SHA-256 hash only
- Admin endpoints protected by `ADMIN_SECRET` env var (simple bearer check)
- User pushes to GitHub — plan provides only `git add` / `git commit` commands

---

## File Map

| File | Purpose |
|---|---|
| `pyproject.toml` | Add sqlalchemy, alembic; move httpx to main deps; add mypy plugin |
| `.env.example` | Add OLLAMA_BASE_URL, OLLAMA_DEFAULT_MODEL, OLLAMA_TIMEOUT_S, ADMIN_SECRET |
| `src/prism/config.py` | Add ollama + admin_secret settings |
| `src/prism/db/__init__.py` | Empty |
| `src/prism/db/models.py` | Team, ApiKey, ModelRoute, RequestLog ORM models |
| `src/prism/db/session.py` | Async engine + session factory + `get_db` dependency |
| `alembic/env.py` | Async Alembic migration runner (replaces generated default) |
| `alembic/versions/0001_initial_schema.py` | Creates all four tables + seeds model_routes |
| `src/prism/core/__init__.py` | Empty |
| `src/prism/core/security.py` | `generate_api_key()`, `hash_key()` — pure functions |
| `src/prism/api/admin.py` | POST /admin/teams, POST /admin/keys, DELETE /admin/keys/{id} |
| `src/prism/core/auth.py` | `validate_api_key` FastAPI dependency; Redis rate-limit check |
| `src/prism/providers/__init__.py` | Empty |
| `src/prism/providers/base.py` | `ChatResponse` dataclass + `BaseProvider` ABC |
| `src/prism/providers/ollama_provider.py` | httpx client wrapping Ollama's `/v1/chat/completions` |
| `src/prism/core/cost.py` | Pricing table + `calculate_cost()` pure function |
| `src/prism/api/chat.py` | `POST /v1/chat/completions` — full request lifecycle |
| `src/prism/main.py` | Add lifespan (DB engine teardown), mount new routers |
| `src/tests/unit/__init__.py` | Empty |
| `src/tests/unit/test_security.py` | Unit tests for generate_api_key, hash_key |
| `src/tests/unit/test_cost.py` | Unit tests for calculate_cost |
| `src/tests/integration/__init__.py` | Empty |
| `src/tests/integration/test_admin.py` | Integration tests for admin endpoints |
| `src/tests/integration/test_chat.py` | End-to-end chat test (requires Ollama) |
| `src/tests/conftest.py` | Add `db` async fixture |

---

## Task 1: Database layer — models, session, Alembic migration

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/prism/config.py`
- Modify: `.env.example`
- Create: `src/prism/db/__init__.py`
- Create: `src/prism/db/models.py`
- Create: `src/prism/db/session.py`
- Create: `alembic/env.py` (after `alembic init alembic`)
- Create: `alembic/versions/0001_initial_schema.py`

**Interfaces:**
- Produces:
  - `from prism.db.models import Team, ApiKey, ModelRoute, RequestLog`
  - `from prism.db.session import get_db, AsyncSessionLocal, engine`
  - All four Postgres tables created; `model_routes` seeded with one Ollama route

---

- [ ] **Step 1: Update pyproject.toml**

Replace the `[project]` and `[tool.mypy]` sections (keep everything else):

```toml
[project]
name = "prism"
version = "0.2.0"
description = "Production LLM gateway with routing, caching, guardrails, and observability"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic-settings>=2.3.0",
    "asyncpg>=0.29.0",
    "redis>=5.0.0",
    "sqlalchemy[asyncio]>=2.0.30",
    "alembic>=1.13.0",
    "httpx>=0.27.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.4.9",
    "mypy>=1.10.0",
    "pre-commit>=3.7.0",
]
```

And update `[tool.mypy]`:

```toml
[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true
plugins = ["sqlalchemy.ext.mypy.plugin"]
```

- [ ] **Step 2: Update .env.example**

Append these lines:

```
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_DEFAULT_MODEL=llama3.2:3b
OLLAMA_TIMEOUT_S=60.0
ADMIN_SECRET=change-me-in-production
```

Also add them to your local `.env` file.

- [ ] **Step 3: Update src/prism/config.py**

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

    ollama_base_url: str = "http://localhost:11434"
    ollama_default_model: str = "llama3.2:3b"
    ollama_timeout_s: float = 60.0

    admin_secret: str = "change-me-in-production"

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

- [ ] **Step 4: Reinstall dependencies**

```bash
uv pip install -e ".[dev]"
```

- [ ] **Step 5: Create src/prism/db/__init__.py** (empty)

- [ ] **Step 6: Write src/prism/db/models.py**

```python
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import TIMESTAMPTZ, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    monthly_budget_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("50.00")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now()
    )

    api_keys: Mapped[list["ApiKey"]] = relationship("ApiKey", back_populates="team")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False
    )
    key_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String, nullable=False)
    rate_limit_rpm: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)

    team: Mapped["Team"] = relationship("Team", back_populates="api_keys")
    request_logs: Mapped[list["RequestLog"]] = relationship(
        "RequestLog", back_populates="api_key"
    )


class ModelRoute(Base):
    __tablename__ = "model_routes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    virtual_model: Mapped[str] = mapped_column(String, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    real_model: Mapped[str] = mapped_column(String, nullable=False)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=20000)


class RequestLog(Base):
    __tablename__ = "request_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    api_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id"), nullable=False
    )
    virtual_model: Mapped[str] = mapped_column(String, nullable=False)
    provider_used: Mapped[str] = mapped_column(String, nullable=False)
    fallback_triggered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    guardrail_flag: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, nullable=False, server_default=func.now()
    )

    api_key: Mapped["ApiKey"] = relationship("ApiKey", back_populates="request_logs")
```

- [ ] **Step 7: Write src/prism/db/session.py**

```python
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from prism.config import settings

engine = create_async_engine(settings.sqlalchemy_url, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

- [ ] **Step 8: Initialize Alembic**

```bash
alembic init alembic
```

This creates `alembic/` directory and `alembic.ini`.

- [ ] **Step 9: Replace alembic/env.py with async version**

```python
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from prism.config import settings
from prism.db.models import Base  # noqa: F401 — imports all models for autogenerate

config = context.config
config.set_main_option("sqlalchemy.url", settings.sqlalchemy_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 10: Start Postgres and generate the migration**

```bash
docker-compose up -d postgres
alembic revision --autogenerate -m "initial schema"
```

This creates a file in `alembic/versions/`. Open it and verify it contains `CREATE TABLE` statements for all four tables.

- [ ] **Step 11: Add seed data to the generated migration**

Open the generated migration file. Add these lines to the `upgrade()` function, AFTER the `op.create_table(...)` calls:

```python
import uuid as _uuid
from alembic import op

def upgrade() -> None:
    # ... existing CREATE TABLE statements generated by alembic ...

    # Seed default model route: virtual model "fast" → Ollama llama3.2:3b
    op.execute(
        "INSERT INTO model_routes (id, virtual_model, priority, provider, real_model, timeout_ms) "
        "VALUES ('" + str(_uuid.uuid4()) + "', 'fast', 1, 'ollama', 'llama3.2:3b', 30000)"
    )
```

- [ ] **Step 12: Run the migration**

```bash
alembic upgrade head
```

Expected output ends with: `Running upgrade  -> <revision>, initial schema`

- [ ] **Step 13: Verify tables exist**

```bash
docker-compose exec postgres psql -U prism -d prism -c "\dt"
```

Expected: lists `api_keys`, `model_routes`, `request_log`, `teams`.

```bash
docker-compose exec postgres psql -U prism -d prism -c "SELECT * FROM model_routes;"
```

Expected: one row with `virtual_model=fast`, `provider=ollama`, `real_model=llama3.2:3b`.

- [ ] **Step 14: Type-check**

```bash
mypy src/prism/db/models.py src/prism/db/session.py src/prism/config.py
```

Expected: `Success: no issues found in 3 source files`

- [ ] **Step 15: Commit**

```bash
git add pyproject.toml .env.example src/prism/config.py src/prism/db/ alembic/ alembic.ini
git commit -m "feat: add SQLAlchemy models, async session, and Alembic migration with seed data"
```

---

## Task 2: API key security utilities + admin endpoints

**Files:**
- Create: `src/prism/core/__init__.py`
- Create: `src/prism/core/security.py`
- Create: `src/prism/api/admin.py`
- Create: `src/tests/unit/__init__.py`
- Create: `src/tests/unit/test_security.py`
- Create: `src/tests/integration/__init__.py`
- Create: `src/tests/integration/test_admin.py`
- Modify: `src/prism/main.py`
- Modify: `src/tests/conftest.py`

**Interfaces:**
- Consumes: `Team`, `ApiKey` models; `get_db` dependency; `settings.admin_secret`
- Produces:
  - `generate_api_key() -> tuple[str, str, str]` — `(raw_key, key_hash, key_prefix)`
  - `hash_key(raw_key: str) -> str`
  - `POST /admin/teams` → `{"id": "...", "name": "..."}`
  - `POST /admin/keys` → `{"id": "...", "key": "prism_...", "key_prefix": "prism_xxxxxxxx"}`
  - `DELETE /admin/keys/{id}` → `{"revoked": true}`

---

- [ ] **Step 1: Write the failing unit tests for security**

`src/tests/unit/__init__.py` — empty

`src/tests/unit/test_security.py`:

```python
from prism.core.security import generate_api_key, hash_key


def test_generate_api_key_format() -> None:
    raw_key, key_hash, key_prefix = generate_api_key()
    assert raw_key.startswith("prism_")
    assert len(raw_key) > 20
    assert key_prefix.startswith("prism_")
    assert len(key_prefix) == 14  # "prism_" + 8 chars


def test_generate_api_key_is_unique() -> None:
    key1, _, _ = generate_api_key()
    key2, _, _ = generate_api_key()
    assert key1 != key2


def test_hash_key_is_deterministic() -> None:
    raw = "prism_test_key"
    assert hash_key(raw) == hash_key(raw)


def test_hash_key_differs_from_raw() -> None:
    raw = "prism_test_key"
    assert hash_key(raw) != raw


def test_hash_key_length() -> None:
    raw = "prism_test_key"
    assert len(hash_key(raw)) == 64  # SHA-256 hex digest
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest src/tests/unit/test_security.py -v
```

Expected: `ImportError` — `prism.core.security` does not exist yet.

- [ ] **Step 3: Create src/prism/core/__init__.py** (empty)

- [ ] **Step 4: Write src/prism/core/security.py**

```python
import hashlib
import secrets


def generate_api_key() -> tuple[str, str, str]:
    token = secrets.token_urlsafe(32)
    raw_key = f"prism_{token}"
    key_prefix = f"prism_{token[:8]}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    return raw_key, key_hash, key_prefix


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()
```

- [ ] **Step 5: Run unit tests to verify they pass**

```bash
pytest src/tests/unit/test_security.py -v
```

Expected: 5 tests PASSED.

- [ ] **Step 6: Write the failing integration tests for admin endpoints**

`src/tests/integration/__init__.py` — empty

`src/tests/integration/test_admin.py`:

```python
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
    # Create team first
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

    # Raw key should NOT be stored in DB — only hash
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

    await db.refresh(await db.get(ApiKey, uuid.UUID(key_id)))  # type: ignore[arg-type]
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
```

- [ ] **Step 7: Run to verify they fail**

```bash
pytest src/tests/integration/test_admin.py -v -m integration
```

Expected: `ImportError` — admin router not wired yet.

- [ ] **Step 8: Write src/prism/api/admin.py**

```python
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prism.config import settings
from prism.core.security import generate_api_key
from prism.db.models import ApiKey, Team
from prism.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])
_bearer = HTTPBearer()


def require_admin(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> None:
    if credentials.credentials != settings.admin_secret:
        raise HTTPException(status_code=401, detail="Invalid admin secret")


class CreateTeamRequest(BaseModel):
    name: str
    monthly_budget_usd: float = 50.0


class CreateKeyRequest(BaseModel):
    team_id: uuid.UUID
    rate_limit_rpm: int = 60


@router.post("/teams", status_code=201, dependencies=[Depends(require_admin)])
async def create_team(
    body: CreateTeamRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    team = Team(name=body.name, monthly_budget_usd=body.monthly_budget_usd)  # type: ignore[arg-type]
    db.add(team)
    await db.commit()
    await db.refresh(team)
    return {"id": str(team.id), "name": team.name}


@router.post("/keys", status_code=201, dependencies=[Depends(require_admin)])
async def create_key(
    body: CreateKeyRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    result = await db.execute(select(Team).where(Team.id == body.team_id))
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")

    raw_key, key_hash, key_prefix = generate_api_key()
    api_key = ApiKey(
        team_id=body.team_id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        rate_limit_rpm=body.rate_limit_rpm,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    return {
        "id": str(api_key.id),
        "key": raw_key,
        "key_prefix": key_prefix,
    }


@router.delete("/keys/{key_id}", dependencies=[Depends(require_admin)])
async def revoke_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=404, detail="Key not found")

    api_key.is_active = False
    api_key.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    return {"revoked": True}
```

- [ ] **Step 9: Add db fixture to conftest.py and update main.py**

Update `src/tests/conftest.py`:

```python
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from prism.db.session import AsyncSessionLocal


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: requires docker-compose services running (postgres + redis)",
    )


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

Update `src/prism/main.py`:

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI

from prism.api.admin import router as admin_router
from prism.api.health import router as health_router
from prism.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    await engine.dispose()


app = FastAPI(title="Prism LLM Gateway", version="0.2.0", lifespan=lifespan)

app.include_router(health_router)
app.include_router(admin_router)
```

- [ ] **Step 10: Run integration tests**

```bash
pytest src/tests/integration/test_admin.py -v -m integration
```

Expected: 4 tests PASSED.

- [ ] **Step 11: Type-check**

```bash
mypy src/prism/core/security.py src/prism/api/admin.py src/prism/main.py
```

Expected: `Success: no issues found in 3 source files`

- [ ] **Step 12: Commit**

```bash
git add src/prism/core/ src/prism/api/admin.py src/prism/main.py src/tests/
git commit -m "feat: add API key generation, admin endpoints for teams and keys"
```

---

## Task 3: Auth FastAPI dependency

**Files:**
- Create: `src/prism/core/auth.py`
- Create: `src/tests/unit/test_auth.py`

**Interfaces:**
- Consumes: `ApiKey` model, `get_db`, `settings.redis_url`, `hash_key()`
- Produces:
  - `validate_api_key` — FastAPI dependency returning `ApiKey` on success; raises `401` for invalid/inactive key; raises `429` when rate limit exceeded

---

- [ ] **Step 1: Write the failing unit tests**

`src/tests/unit/test_auth.py`:

```python
import pytest

from prism.core.auth import check_rate_limit_key


def test_rate_limit_key_format() -> None:
    key = check_rate_limit_key("abc-123", 100)
    # just verifying the key includes the api_key_id
    assert "abc-123" in key


def test_rate_limit_key_includes_minute_bucket() -> None:
    import time

    minute = int(time.time() // 60)
    key = check_rate_limit_key("abc-123", 100)
    assert str(minute) in key
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest src/tests/unit/test_auth.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Write src/prism/core/auth.py**

```python
import time
import uuid

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prism.config import settings
from prism.core.security import hash_key
from prism.db.models import ApiKey
from prism.db.session import get_db

_bearer = HTTPBearer()


def check_rate_limit_key(api_key_id: str, limit_rpm: int) -> str:
    minute = int(time.time() // 60)
    return f"rl:{api_key_id}:{minute}:{limit_rpm}"


async def _check_rate_limit(api_key_id: uuid.UUID, limit_rpm: int) -> bool:
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    key = f"rl:{api_key_id}:{int(time.time() // 60)}"
    try:
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, 60)
        return int(count) <= limit_rpm
    finally:
        await r.aclose()


async def validate_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    key_hash = hash_key(credentials.credentials)
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.key_hash == key_hash,
            ApiKey.is_active.is_(True),
        )
    )
    api_key = result.scalar_one_or_none()

    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    if not await _check_rate_limit(api_key.id, api_key.rate_limit_rpm):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    return api_key
```

- [ ] **Step 4: Run unit tests**

```bash
pytest src/tests/unit/test_auth.py -v
```

Expected: 2 tests PASSED.

- [ ] **Step 5: Type-check**

```bash
mypy src/prism/core/auth.py
```

Expected: `Success: no issues found in 1 source file`

- [ ] **Step 6: Commit**

```bash
git add src/prism/core/auth.py src/tests/unit/test_auth.py
git commit -m "feat: add auth dependency with API key validation and Redis rate limiting"
```

---

## Task 4: Ollama provider + cost calculator

**Files:**
- Create: `src/prism/providers/__init__.py`
- Create: `src/prism/providers/base.py`
- Create: `src/prism/providers/ollama_provider.py`
- Create: `src/prism/core/cost.py`
- Create: `src/tests/unit/test_cost.py`

**Interfaces:**
- Produces:
  - `ChatResult` dataclass with `content`, `prompt_tokens`, `completion_tokens`, `raw`
  - `OllamaProvider.chat(messages, model, **kwargs) -> ChatResult`
  - `calculate_cost(provider, model, prompt_tokens, completion_tokens) -> Decimal`

---

- [ ] **Step 1: Write failing unit tests for cost calculator**

`src/tests/unit/test_cost.py`:

```python
from decimal import Decimal

from prism.core.cost import calculate_cost


def test_ollama_is_free() -> None:
    cost = calculate_cost("ollama", "llama3.2:3b", prompt_tokens=100, completion_tokens=50)
    assert cost == Decimal("0")


def test_openai_gpt4o_mini_cost() -> None:
    # $0.15 per million input, $0.60 per million output
    cost = calculate_cost(
        "openai", "gpt-4o-mini", prompt_tokens=1_000_000, completion_tokens=1_000_000
    )
    assert cost == Decimal("0.75")  # 0.15 + 0.60


def test_unknown_provider_returns_zero() -> None:
    cost = calculate_cost("unknown", "mystery-model", prompt_tokens=500, completion_tokens=200)
    assert cost == Decimal("0")


def test_cost_scales_with_tokens() -> None:
    cost_small = calculate_cost("openai", "gpt-4o-mini", prompt_tokens=100, completion_tokens=50)
    cost_large = calculate_cost("openai", "gpt-4o-mini", prompt_tokens=1000, completion_tokens=500)
    assert cost_large > cost_small
    assert cost_large == cost_small * 10
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest src/tests/unit/test_cost.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create src/prism/providers/__init__.py** (empty)

- [ ] **Step 4: Write src/prism/providers/base.py**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ChatResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    raw: dict[str, object]


class BaseProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: object,
    ) -> ChatResult: ...
```

- [ ] **Step 5: Write src/prism/providers/ollama_provider.py**

```python
import httpx

from prism.config import settings
from prism.providers.base import BaseProvider, ChatResult


class OllamaProvider(BaseProvider):
    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        **kwargs: object,
    ) -> ChatResult:
        async with httpx.AsyncClient(timeout=settings.ollama_timeout_s) as client:
            response = await client.post(
                f"{settings.ollama_base_url}/v1/chat/completions",
                json={"model": model, "messages": messages, **kwargs},
            )
            response.raise_for_status()

        data: dict[str, object] = response.json()
        usage = data.get("usage") or {}
        assert isinstance(usage, dict)
        choices = data.get("choices") or []
        assert isinstance(choices, list)
        first_choice = choices[0]
        assert isinstance(first_choice, dict)
        message = first_choice.get("message") or {}
        assert isinstance(message, dict)

        return ChatResult(
            content=str(message.get("content", "")),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            raw=data,
        )
```

- [ ] **Step 6: Write src/prism/core/cost.py**

```python
from decimal import Decimal

# Rates per million tokens (input, output) in USD
_PRICING: dict[tuple[str, str], tuple[float, float]] = {
    ("ollama", "*"): (0.0, 0.0),
    ("openai", "gpt-4o-mini"): (0.15, 0.60),
    ("anthropic", "claude-haiku-4-5-20251001"): (0.25, 1.25),
}


def calculate_cost(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> Decimal:
    rates = _PRICING.get((provider, model)) or _PRICING.get((provider, "*")) or (0.0, 0.0)
    input_rate, output_rate = rates
    cost = (input_rate * prompt_tokens + output_rate * completion_tokens) / 1_000_000
    return Decimal(str(round(cost, 10)))
```

- [ ] **Step 7: Run unit tests**

```bash
pytest src/tests/unit/test_cost.py -v
```

Expected: 4 tests PASSED.

- [ ] **Step 8: Type-check**

```bash
mypy src/prism/providers/base.py src/prism/providers/ollama_provider.py src/prism/core/cost.py
```

Expected: `Success: no issues found in 3 source files`

- [ ] **Step 9: Commit**

```bash
git add src/prism/providers/ src/prism/core/cost.py src/tests/unit/test_cost.py
git commit -m "feat: add Ollama provider and cost calculator"
```

---

## Task 5: /v1/chat/completions endpoint + request logging

**Files:**
- Create: `src/prism/api/chat.py`
- Create: `src/tests/integration/test_chat.py`
- Modify: `src/prism/main.py`

**Interfaces:**
- Consumes: `validate_api_key`, `get_db`, `OllamaProvider`, `calculate_cost`, `ModelRoute`, `RequestLog`
- Produces:
  - `POST /v1/chat/completions` → OpenAI-compatible JSON + `prism_metadata` block
  - One `request_log` row written per request

---

- [ ] **Step 1: Write the failing integration test**

`src/tests/integration/test_chat.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prism.db.models import RequestLog
from prism.main import app

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
                "messages": [{"role": "user", "content": "Reply with just the word PONG"}],
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )

    assert response.status_code == 200
    data = response.json()

    # OpenAI-compatible shape
    assert "choices" in data
    assert "usage" in data
    assert data["usage"]["prompt_tokens"] > 0

    # Prism metadata
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
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest src/tests/integration/test_chat.py -v -m integration
```

Expected: `ImportError` — `prism.api.chat` doesn't exist yet.

- [ ] **Step 3: Write src/prism/api/chat.py**

```python
import time
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prism.config import settings
from prism.core.auth import validate_api_key
from prism.core.cost import calculate_cost
from prism.db.models import ApiKey, ModelRoute, RequestLog
from prism.db.session import get_db
from prism.providers.ollama_provider import OllamaProvider

router = APIRouter(tags=["gateway"])
_ollama = OllamaProvider()


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
        raise HTTPException(status_code=400, detail="Streaming not supported in Phase 1")

    start = time.perf_counter()

    result = await db.execute(
        select(ModelRoute)
        .where(ModelRoute.virtual_model == body.model)
        .order_by(ModelRoute.priority)
        .limit(1)
    )
    route = result.scalar_one_or_none()

    provider_name = route.provider if route else "ollama"
    real_model = route.real_model if route else settings.ollama_default_model

    if provider_name != "ollama":
        raise HTTPException(
            status_code=503, detail=f"Provider {provider_name} not available in Phase 1"
        )

    chat_result = await _ollama.chat(
        messages=[m.model_dump() for m in body.messages],
        model=real_model,
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
            "fallback_triggered": False,
            "cost_usd": float(cost),
            "latency_ms": latency_ms,
        },
    }
```

- [ ] **Step 4: Wire chat router into main.py**

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI

from prism.api.admin import router as admin_router
from prism.api.chat import router as chat_router
from prism.api.health import router as health_router
from prism.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    await engine.dispose()


app = FastAPI(title="Prism LLM Gateway", version="0.2.0", lifespan=lifespan)

app.include_router(health_router)
app.include_router(admin_router)
app.include_router(chat_router)
```

- [ ] **Step 5: Make sure Ollama is running with the right model**

```bash
ollama serve &          # start if not already running
ollama pull llama3.2:3b # pull if not already present
```

Verify: `curl http://localhost:11434/v1/models` should list `llama3.2:3b`.

- [ ] **Step 6: Run all integration tests**

```bash
docker-compose up -d postgres redis
pytest src/tests/integration/test_chat.py -v -m integration
```

Expected: 3 tests PASSED (last one is fast — no Ollama call needed).

- [ ] **Step 7: Type-check the full src**

```bash
mypy src/prism/
```

Expected: `Success: no issues found`

- [ ] **Step 8: Run full test suite**

```bash
pytest src/tests/ -v -m "not integration"
```

Expected: all unit tests PASSED.

- [ ] **Step 9: Commit**

```bash
git add src/prism/api/chat.py src/prism/main.py src/tests/integration/test_chat.py
git commit -m "feat: add /v1/chat/completions endpoint with Ollama routing and request logging"
```

---

## Phase 1 Complete — Demo Gate

With `docker-compose up -d postgres redis` and `ollama serve` running:

```bash
# Start Prism
uvicorn prism.main:app --reload

# Create a team
curl -s -X POST http://localhost:8000/admin/teams \
  -H "Authorization: Bearer change-me-in-production" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-team"}' | python3 -m json.tool

# Issue an API key (copy the "key" value from the output)
curl -s -X POST http://localhost:8000/admin/keys \
  -H "Authorization: Bearer change-me-in-production" \
  -H "Content-Type: application/json" \
  -d '{"team_id": "<team-id-from-above>"}' | python3 -m json.tool

# Make a chat request
curl -s -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer <your-prism-key>" \
  -H "Content-Type: application/json" \
  -d '{"model": "fast", "messages": [{"role": "user", "content": "Say hello"}]}' | python3 -m json.tool

# Verify it was logged in Postgres
docker-compose exec postgres psql -U prism -d prism \
  -c "SELECT virtual_model, provider_used, prompt_tokens, cost_usd, latency_ms FROM request_log;"
```

**Expected:** response includes `prism_metadata` block + a row appears in `request_log`.

**GitHub commit message for push:** `feat: Phase 1 — core proxy with Ollama, auth, and request logging`

**Next:** Phase 2 plan — mock OpenAI + Anthropic providers, virtual model config, fallback chain, circuit breaker.
