import asyncio
import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.main as main
from app.core.config import Settings, get_settings
from app.core.tokens import create_access_token
from app.modules.catalog.models import Category
from app.modules.users.models import User, UserRole

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)

SECRET = "test-only-secret-" * 3
URL = "/api/v1/categories"


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


async def create_headers(db_session: AsyncSession, role: UserRole) -> dict[str, str]:
    user = User(
        email=f"{role.value}@example.com", password_hash="test-hash", full_name="User", role=role
    )
    db_session.add(user)
    await db_session.commit()
    token = create_access_token(user.id, Settings(_env_file=None, jwt_secret=SECRET))
    return {"Authorization": f"Bearer {token}"}


async def test_public_list_detail_and_missing_category(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    assert (await client.get(URL)).json() == []
    category = Category(name="Books", slug="books")
    db_session.add(category)
    await db_session.commit()
    category_id = str(category.id)

    listing = await client.get(URL)
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [category_id]
    detail = await client.get(f"{URL}/{category_id}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "Books"
    assert detail.json()["slug"] == "books"
    missing = await client.get(f"{URL}/{uuid4()}")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Category not found."}
    assert (await client.get(f"{URL}/not-a-uuid")).status_code == 422


async def test_only_admin_can_create_and_update(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    category = Category(name="Books", slug="books")
    db_session.add(category)
    await db_session.commit()
    category_id = str(category.id)
    payload = {"name": "Music", "slug": "music"}

    assert (await client.post(URL, json=payload)).status_code == 401
    assert (await client.patch(f"{URL}/{category_id}", json={"name": "Changed"})).status_code == 401
    for role in (UserRole.CUSTOMER, UserRole.MANAGER):
        headers = await create_headers(db_session, role)
        assert (await client.post(URL, json=payload, headers=headers)).status_code == 403
        assert (
            await client.patch(f"{URL}/{category_id}", json={"name": "Changed"}, headers=headers)
        ).status_code == 403

    headers = await create_headers(db_session, UserRole.ADMIN)
    created = await client.post(URL, json=payload, headers=headers)
    assert created.status_code == 201
    assert created.json()["name"] == "Music"
    changed = await client.patch(
        f"{URL}/{category_id}", json={"name": "New Books"}, headers=headers
    )
    assert changed.status_code == 200
    assert changed.json()["name"] == "New Books"
    assert changed.json()["slug"] == "books"


async def test_admin_errors_and_conflicts(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await create_headers(db_session, UserRole.ADMIN)
    first = await client.post(URL, json={"name": "Books", "slug": "books"}, headers=headers)
    second = await client.post(URL, json={"name": "Music", "slug": "music"}, headers=headers)
    assert first.status_code == second.status_code == 201
    conflict = await client.post(URL, json={"name": "Other", "slug": "books"}, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "Category slug is already in use."}
    conflict = await client.patch(
        f"{URL}/{second.json()['id']}", json={"name": "Changed", "slug": "books"}, headers=headers
    )
    assert conflict.status_code == 409
    unchanged = await client.get(f"{URL}/{second.json()['id']}")
    assert unchanged.json()["name"] == "Music"
    assert unchanged.json()["slug"] == "music"
    assert (
        await client.patch(f"{URL}/{uuid4()}", json={"name": "Missing"}, headers=headers)
    ).status_code == 404
    assert (
        await client.post(URL, json={"name": "Books", "slug": "Bad slug"}, headers=headers)
    ).status_code == 422
    assert (
        await client.patch(f"{URL}/{first.json()['id']}", json={}, headers=headers)
    ).status_code == 422


async def test_concurrent_creation_with_same_slug(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await create_headers(db_session, UserRole.ADMIN)
    payload = {"name": "Books", "slug": "books"}
    responses = await asyncio.gather(
        client.post(URL, json=payload, headers=headers),
        client.post(URL, json=payload, headers=headers),
    )
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert await db_session.scalar(select(func.count()).select_from(Category)) == 1
