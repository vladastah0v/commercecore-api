import asyncio
import os
from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.main as main
from app.core.config import Settings
from app.core.security import verify_password
from app.modules.users.models import User
from app.modules.users.repository import UserRepository

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)

URL = "/api/v1/auth/register"
PAYLOAD = {"email": " USER@Example.com ", "password": "valid-password", "full_name": " Test User "}


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, monkeypatch) -> AsyncIterator[AsyncClient]:
    settings = Settings(_env_file=None)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    async with main.app.router.lifespan_context(main.app):
        async with AsyncClient(
            transport=ASGITransport(app=main.app), base_url="http://test"
        ) as api_client:
            yield api_client


async def test_register_returns_public_user_and_stores_password_hash(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await client.post(URL, json=PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id",
        "email",
        "full_name",
        "role",
        "is_active",
        "created_at",
        "updated_at",
    }
    assert body["email"] == "user@example.com"
    assert body["full_name"] == "Test User"
    assert body["role"] == "customer"
    assert body["is_active"] is True
    assert datetime.fromisoformat(body["created_at"]).utcoffset() is not None
    assert "valid-password" not in response.text
    saved = await db_session.get(User, UUID(body["id"]))
    assert saved is not None
    assert saved.password_hash.startswith("$argon2id$")
    assert await verify_password("valid-password", saved.password_hash)


async def test_duplicate_email_returns_conflict(client: AsyncClient) -> None:
    assert (await client.post(URL, json=PAYLOAD)).status_code == 201

    response = await client.post(URL, json={**PAYLOAD, "email": "user@EXAMPLE.COM"})

    assert response.status_code == 409
    assert response.json() == {"detail": "A user with this email is already registered."}
    assert "valid-password" not in response.text


async def test_concurrent_requests_create_one_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    responses = await asyncio.gather(client.post(URL, json=PAYLOAD), client.post(URL, json=PAYLOAD))

    assert sorted(response.status_code for response in responses) == [201, 409]
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.parametrize("changes", [{"role": "admin"}, {"password": "BadPwd1"}])
async def test_invalid_input_is_rejected_without_echoing_password(
    client: AsyncClient, db_session: AsyncSession, changes: dict[str, str]
) -> None:
    payload = {**PAYLOAD, **changes}
    response = await client.post(URL, json=payload)

    assert response.status_code == 422
    assert payload["password"] not in response.text
    assert all("input" not in error for error in response.json()["detail"])
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


async def test_database_errors_do_not_expose_sql_or_password(
    client: AsyncClient, monkeypatch, caplog
) -> None:
    async def fail_to_add(repository: UserRepository, user: User) -> None:
        raise IntegrityError("sensitive SQL", {"password": "valid-password"}, Exception("db error"))

    monkeypatch.setattr(UserRepository, "add", fail_to_add)
    response = await client.post(URL, json=PAYLOAD)

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "valid-password" not in response.text
    assert "sensitive SQL" not in response.text
    assert "valid-password" not in caplog.text
    assert "sensitive SQL" not in caplog.text


async def test_registration_is_in_openapi(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert "post" in response.json()["paths"][URL]
