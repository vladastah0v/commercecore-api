import os
from collections.abc import AsyncIterator
from hashlib import sha256

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.main as main
from app.core.config import Settings, get_settings
from app.core.tokens import decode_token
from app.modules.auth.models import RefreshToken
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


async def test_login_issues_tokens_and_stores_only_refresh_hash(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    created = await client.post("/api/v1/auth/register", json=REGISTRATION)
    assert created.status_code == 201
    response = await client.post(
        "/api/v1/auth/login", json={"email": " USER@EXAMPLE.COM ", "password": "valid-password"}
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"access_token", "refresh_token", "token_type"}
    assert body["token_type"] == "bearer"
    settings = Settings(_env_file=None, jwt_secret="test-only-secret-" * 3)
    access = decode_token(body["access_token"], "access", settings)
    refresh = decode_token(body["refresh_token"], "refresh", settings)
    assert str(access.user_id) == str(refresh.user_id) == created.json()["id"]
    saved = await db_session.scalar(select(RefreshToken))
    assert saved is not None
    assert saved.token_hash == sha256(body["refresh_token"].encode()).hexdigest()
    assert saved.token_hash != body["refresh_token"]
    assert saved.expires_at == refresh.expires_at
    assert saved.revoked_at is None


async def test_wrong_password_and_unknown_email_return_same_response(client: AsyncClient) -> None:
    assert (await client.post("/api/v1/auth/register", json=REGISTRATION)).status_code == 201
    wrong = await client.post(
        "/api/v1/auth/login", json={"email": "user@example.com", "password": "incorrect"}
    )
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": "absent@example.com", "password": "incorrect"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Invalid email or password."}


async def test_inactive_user_cannot_log_in(client: AsyncClient, db_session: AsyncSession) -> None:
    assert (await client.post("/api/v1/auth/register", json=REGISTRATION)).status_code == 201
    user = await db_session.scalar(select(User).where(User.email == "user@example.com"))
    assert user is not None
    user.is_active = False
    await db_session.commit()
    response = await client.post(
        "/api/v1/auth/login", json={"email": "user@example.com", "password": "valid-password"}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password."}
    assert await db_session.scalar(select(RefreshToken)) is None
