from prism.config import Settings, settings


def test_postgres_defaults() -> None:
    # Field defaults, not the live singleton — the singleton reflects
    # whatever POSTGRES_* env vars the running process was started with
    # (e.g. testcontainers-assigned ports during the test session).
    defaults = Settings.model_fields
    assert defaults["postgres_host"].default == "localhost"
    assert defaults["postgres_port"].default == 5432
    assert defaults["postgres_user"].default == "prism"
    assert defaults["postgres_db"].default == "prism"


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
    assert Settings.model_fields["redis_url"].default == "redis://localhost:6379"
