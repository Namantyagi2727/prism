from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from prism.config import settings
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: requires docker-compose services running (postgres + redis)",
    )


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    # NullPool prevents connection reuse across event loop boundaries in tests
    engine = create_async_engine(settings.sqlalchemy_url, poolclass=NullPool)
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    async with session_factory() as session:
        yield session
    await engine.dispose()
