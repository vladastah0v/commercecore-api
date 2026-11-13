import asyncio
import os
from collections.abc import AsyncIterator
from hashlib import sha256

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.main as main
from app.core.config import Settings, get_settings
from app.core.tokens import decode_token
from app.modules.auth.models import RefreshToken
from app.modules.auth.repository import RefreshTokenRepository
from app.modules.users.models import User

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)

REGISTRATION = {"email": "user@example.com", "password": "valid-password", "full_name": "Test User"}


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, monkeypatch) -> AsyncIterator[AsyncClient]:
    settings = Settings(_env_file=None, jwt_secret="test-only-secret-" * 3)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setitem(main.app.dependency_overrides, get_settings, lambda: settings)
    async with main.app.router.lifespan_context(main.app):
        async with AsyncClient(
            transport=ASGITransport(app=main.app), base_url="http://test"
        ) as api:
            yield api


async def login(client: AsyncClient) -> dict[str, str]:
    assert (await client.post("/api/v1/auth/register", json=REGISTRATION)).status_code == 201
    response = await client.post(
        "/api/v1/auth/login", json={"email": "user@example.com", "password": "valid-password"}
    )
    assert response.status_code == 200
    return response.json()


async def test_rotation_revokes_old_token_and_stores_new_hash(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    original = await login(client)
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]}
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    rotated = response.json()
    assert rotated["refresh_token"] != original["refresh_token"]
    settings = Settings(_env_file=None, jwt_secret="test-only-secret-" * 3)
    assert (
        decode_token(rotated["access_token"], "access", settings).user_id
        == decode_token(rotated["refresh_token"], "refresh", settings).user_id
    )
    records = (await db_session.scalars(select(RefreshToken))).all()
    by_hash = {record.token_hash: record for record in records}
    old_hash = sha256(original["refresh_token"].encode()).hexdigest()
    new_hash = sha256(rotated["refresh_token"].encode()).hexdigest()
    assert len(records) == 2
    assert by_hash[old_hash].revoked_at is not None
    assert by_hash[new_hash].revoked_at is None
    replay = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]}
    )
    assert replay.status_code == 401


async def test_concurrent_refresh_allows_only_one_rotation(client: AsyncClient) -> None:
    original = await login(client)
    payload = {"refresh_token": original["refresh_token"]}
    responses = await asyncio.gather(
        client.post("/api/v1/auth/refresh", json=payload),
        client.post("/api/v1/auth/refresh", json=payload),
    )
    assert sorted(response.status_code for response in responses) == [200, 401]


async def test_logout_revokes_refresh_token(client: AsyncClient) -> None:
    original = await login(client)
    payload = {"refresh_token": original["refresh_token"]}
    response = await client.post("/api/v1/auth/logout", json=payload)
    assert response.status_code == 204
    assert not response.content
    assert (await client.post("/api/v1/auth/refresh", json=payload)).status_code == 401
    assert (await client.post("/api/v1/auth/logout", json=payload)).status_code == 401


async def test_invalid_and_access_tokens_cannot_be_used_to_refresh(client: AsyncClient) -> None:
    original = await login(client)
    for token in ("invalid-token", original["access_token"]):
        response = await client.post("/api/v1/auth/refresh", json={"refresh_token": token})
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid refresh token."}
        assert token not in response.text


async def test_inactive_user_cannot_refresh(client: AsyncClient, db_session: AsyncSession) -> None:
    original = await login(client)
    user = await db_session.scalar(select(User).where(User.email == "user@example.com"))
    assert user is not None
    user.is_active = False
    await db_session.commit()
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]}
    )
    assert response.status_code == 401


async def test_failed_rotation_keeps_old_token_usable(client: AsyncClient, monkeypatch) -> None:
    original = await login(client)

    async def fail_to_add(repository: RefreshTokenRepository, token: RefreshToken) -> None:
        raise IntegrityError("sensitive SQL", {}, Exception("db error"))

    with monkeypatch.context() as patch:
        patch.setattr(RefreshTokenRepository, "add", fail_to_add)
        failed = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]}
        )
    assert failed.status_code == 500
    assert original["refresh_token"] not in failed.text
    retry = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]}
    )
    assert retry.status_code == 200
