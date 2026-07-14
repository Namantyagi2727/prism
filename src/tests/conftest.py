import os
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

REPO_ROOT = Path(__file__).resolve().parents[2]

_postgres: PostgresContainer | None = None
_redis: RedisContainer | None = None


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "integration: spins up postgres + redis via testcontainers"
    )
    config.addinivalue_line(
        "markers",
        "requires_ollama: requires a live Ollama server with llama3.2:3b pulled",
    )

    global _postgres, _redis
    _postgres = PostgresContainer(
        "pgvector/pgvector:pg16", username="prism", password="prism", dbname="prism"
    )
    _postgres.start()
    _redis = RedisContainer("redis:7-alpine")
    _redis.start()

    # Must land before the first import of prism.config anywhere in the
    # process — its module-level `settings = Settings()` and the SQLAlchemy
    # engine created at prism.db.session import time both bind immediately.
    os.environ["POSTGRES_HOST"] = _postgres.get_container_host_ip()
    os.environ["POSTGRES_PORT"] = str(_postgres.get_exposed_port(5432))
    os.environ["POSTGRES_USER"] = "prism"
    os.environ["POSTGRES_PASSWORD"] = "prism"
    os.environ["POSTGRES_DB"] = "prism"
    os.environ["REDIS_URL"] = (
        f"redis://{_redis.get_container_host_ip()}:{_redis.get_exposed_port(6379)}"
    )

    from alembic.config import Config

    from alembic import command

    alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    command.upgrade(alembic_cfg, "head")


def pytest_unconfigure(config: pytest.Config) -> None:
    if _redis is not None:
        _redis.stop()
    if _postgres is not None:
        _postgres.stop()


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    from prism.config import settings

    # NullPool prevents connection reuse across event loop boundaries in tests
    engine = create_async_engine(settings.sqlalchemy_url, poolclass=NullPool)
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    async with session_factory() as session:
        yield session
    await engine.dispose()
