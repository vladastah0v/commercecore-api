import asyncio
import os
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

import app.main as main
from app.core.config import Settings, get_settings
from app.modules.auth.exceptions import InvalidCredentialsError
from app.modules.auth.rate_limit import login_rate_key
from app.modules.auth.router import get_login_service

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)

PAYLOAD = {"email": "user@example.com", "password": "wrong-password"}


class InvalidLoginService:
    async def login(self, data):
        raise InvalidCredentialsError


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, monkeypatch) -> AsyncIterator[AsyncClient]:
    settings = Settings(_env_file=None, login_rate_limit=3, login_rate_window_seconds=60)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setitem(main.app.dependency_overrides, get_settings, lambda: settings)
    monkeypatch.setitem(main.app.dependency_overrides, get_login_service, InvalidLoginService)
    async with main.app.router.lifespan_context(main.app):
        async with AsyncClient(
            transport=ASGITransport(app=main.app), base_url="http://test"
        ) as api:
            yield api


async def test_limit_is_atomic_and_ignores_forwarded_header(client: AsyncClient) -> None:
    async def attempt(index: int):
        return await client.post(
            "/api/v1/auth/login", json=PAYLOAD, headers={"X-Forwarded-For": f"192.0.2.{index}"}
        )

    responses = await asyncio.gather(*(attempt(i) for i in range(12)))
    assert sum(response.status_code == 401 for response in responses) == 3
    blocked = [response for response in responses if response.status_code == 429]
    assert len(blocked) == 9
    assert all(1 <= int(response.headers["retry-after"]) <= 60 for response in blocked)
    assert all(response.headers["cache-control"] == "no-store" for response in blocked)
    key = login_rate_key("127.0.0.1")
    assert 0 < await main.app.state.redis.ttl(key) <= 60
    assert "127.0.0.1" not in key


async def test_counter_expires_and_allows_login_again(client: AsyncClient) -> None:
    for _ in range(3):
        assert (await client.post("/api/v1/auth/login", json=PAYLOAD)).status_code == 401
    assert (await client.post("/api/v1/auth/login", json=PAYLOAD)).status_code == 429
    await main.app.state.redis.expire(login_rate_key("127.0.0.1"), 1)
    await asyncio.sleep(1.2)
    assert (await client.post("/api/v1/auth/login", json=PAYLOAD)).status_code == 401


async def test_different_clients_have_independent_limits(client: AsyncClient) -> None:
    for _ in range(3):
        assert (await client.post("/api/v1/auth/login", json=PAYLOAD)).status_code == 401
    assert (await client.post("/api/v1/auth/login", json=PAYLOAD)).status_code == 429
    other_key = login_rate_key("192.0.2.10")
    try:
        await main.app.state.redis.delete(other_key)
        async with AsyncClient(
            transport=ASGITransport(app=main.app, client=("192.0.2.10", 1234)),
            base_url="http://test",
        ) as other:
            assert (await other.post("/api/v1/auth/login", json=PAYLOAD)).status_code == 401
    finally:
        await main.app.state.redis.delete(other_key)


async def test_unavailable_redis_blocks_login(client: AsyncClient, monkeypatch) -> None:
    monkeypatch.setattr(main.app.state.redis, "eval", AsyncMock(side_effect=RedisConnectionError()))
    response = await client.post("/api/v1/auth/login", json=PAYLOAD)
    assert response.status_code == 503
    assert response.json() == {"detail": "Login temporarily unavailable."}
    assert response.headers["cache-control"] == "no-store"
