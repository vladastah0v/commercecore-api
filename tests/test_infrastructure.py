from unittest.mock import AsyncMock, MagicMock

import pytest
from asyncpg import InvalidPasswordError
from httpx import ASGITransport, AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError

import app.main as main
from app.core.config import Settings
from app.core.database import create_database_engine
from app.core.health import check_postgres, check_redis


@pytest.mark.parametrize(
    ("postgres_ok", "redis_ok", "status_code", "status"),
    [
        (True, True, 200, "ok"),
        (False, True, 503, "unavailable"),
        (True, False, 503, "unavailable"),
        (False, False, 503, "unavailable"),
    ],
)
async def test_readiness_reports_service_availability(
    monkeypatch, postgres_ok: bool, redis_ok: bool, status_code: int, status: str
) -> None:
    monkeypatch.setattr(main, "check_postgres", AsyncMock(return_value=postgres_ok))
    monkeypatch.setattr(main, "check_redis", AsyncMock(return_value=redis_ok))

    async with main.app.router.lifespan_context(main.app):
        async with AsyncClient(
            transport=ASGITransport(app=main.app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/health/ready")

    assert response.status_code == status_code
    assert response.json() == {
        "status": status,
        "services": {
            "postgres": "ok" if postgres_ok else "unavailable",
            "redis": "ok" if redis_ok else "unavailable",
        },
    }


async def test_postgres_authentication_failure_is_reported_as_unavailable() -> None:
    engine = MagicMock()
    engine.connect.return_value.__aenter__ = AsyncMock(side_effect=InvalidPasswordError("private"))

    assert await check_postgres(engine) is False


async def test_redis_connection_failure_is_reported_as_unavailable() -> None:
    client = MagicMock()
    client.ping = AsyncMock(side_effect=RedisConnectionError("private"))

    assert await check_redis(client) is False


async def test_lifespan_closes_resources_after_error(monkeypatch) -> None:
    engine = MagicMock()
    engine.dispose = AsyncMock()
    client = MagicMock()
    client.aclose = AsyncMock()
    monkeypatch.setattr(main, "create_database_engine", lambda settings: engine)
    monkeypatch.setattr(main, "create_redis_client", lambda settings: client)

    with pytest.raises(RuntimeError, match="shutdown test"):
        async with main.app.router.lifespan_context(main.app):
            raise RuntimeError("shutdown test")

    client.aclose.assert_awaited_once()
    engine.dispose.assert_awaited_once()


async def test_database_password_with_special_characters_is_preserved(monkeypatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "test:@/password")
    settings = Settings(_env_file=None)
    engine = create_database_engine(settings)
    try:
        assert engine.url.password == "test:@/password"
        assert "test:@/password" not in str(engine.url)
    finally:
        await engine.dispose()
