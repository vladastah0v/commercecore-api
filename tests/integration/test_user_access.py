import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

import jwt
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.main as main
from app.core.config import Settings, get_settings
from app.core.dependencies import require_roles
from app.core.exceptions import register_exception_handlers
from app.core.tokens import create_access_token, create_refresh_token
from app.modules.users.models import User, UserRole

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)

SECRET = "test-only-secret-" * 3
ME = "/api/v1/users/me"


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, monkeypatch) -> AsyncIterator[AsyncClient]:
    settings = Settings(_env_file=None, jwt_secret=SECRET)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setitem(main.app.dependency_overrides, get_settings, lambda: settings)
    async with main.app.router.lifespan_context(main.app):
        async with AsyncClient(
            transport=ASGITransport(app=main.app), base_url="http://test"
        ) as api:
            yield api


async def test_me_returns_current_user_without_password(client: AsyncClient) -> None:
    registration = {"email": "user@example.com", "password": "valid-password", "full_name": "User"}
    created = await client.post("/api/v1/auth/register", json=registration)
    assert created.status_code == 201
    login = await client.post(
        "/api/v1/auth/login", json={"email": "user@example.com", "password": "valid-password"}
    )
    assert login.status_code == 200
    response = await client.get(
        ME, headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    assert response.status_code == 200
    assert response.json()["id"] == created.json()["id"]
    assert response.json()["role"] == "customer"
    assert "password" not in response.json() and "password_hash" not in response.json()


async def test_me_rejects_missing_invalid_expired_refresh_and_unknown_user_tokens(
    client: AsyncClient,
) -> None:
    settings = Settings(_env_file=None, jwt_secret=SECRET)
    now = datetime.now(UTC)
    expired = jwt.encode(
        {
            "sub": str(uuid4()),
            "jti": str(uuid4()),
            "type": "access",
            "iat": now - timedelta(minutes=2),
            "exp": now - timedelta(minutes=1),
        },
        SECRET,
        algorithm="HS256",
    )
    headers = [
        {},
        {"Authorization": "Basic invalid"},
        {"Authorization": "Bearer invalid-token"},
        {"Authorization": f"Bearer {expired}"},
        {"Authorization": f"Bearer {create_refresh_token(uuid4(), settings)}"},
        {"Authorization": f"Bearer {create_access_token(uuid4(), settings)}"},
    ]
    for header in headers:
        response = await client.get(ME, headers=header)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json() == {"detail": "Invalid or missing authentication credentials."}


async def test_inactive_user_is_denied(client: AsyncClient, db_session: AsyncSession) -> None:
    user = User(email="inactive@example.com", password_hash="hash", full_name="User")
    db_session.add(user)
    await db_session.commit()
    token = create_access_token(user.id, Settings(_env_file=None, jwt_secret=SECRET))
    assert (await client.get(ME, headers={"Authorization": f"Bearer {token}"})).status_code == 200
    user.is_active = False
    await db_session.commit()
    response = await client.get(ME, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_role_checks_use_current_database_role(db_session: AsyncSession) -> None:
    settings = Settings(_env_file=None, jwt_secret=SECRET)
    test_app = FastAPI()
    register_exception_handlers(test_app)
    test_app.state.db_session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    test_app.dependency_overrides[get_settings] = lambda: settings

    @test_app.get("/admin")
    async def admin_only(
        user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    ) -> dict[str, str]:
        return {"role": user.role.value}

    @test_app.get("/staff")
    async def staff_only(
        user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER))],
    ) -> dict[str, str]:
        return {"role": user.role.value}

    user = User(email="roles@example.com", password_hash="hash", full_name="User")
    db_session.add(user)
    await db_session.commit()
    token = create_access_token(user.id, settings)
    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as probe:
        assert (await probe.get("/admin", headers=headers)).status_code == 403
        assert (await probe.get("/staff", headers=headers)).status_code == 403
        user.role = UserRole.MANAGER
        await db_session.commit()
        assert (await probe.get("/admin", headers=headers)).status_code == 403
        assert (await probe.get("/staff", headers=headers)).status_code == 200
        user.role = UserRole.ADMIN
        await db_session.commit()
        assert (await probe.get("/admin", headers=headers)).status_code == 200
        assert (await probe.get("/staff", headers=headers)).status_code == 200
