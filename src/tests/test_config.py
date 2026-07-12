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
