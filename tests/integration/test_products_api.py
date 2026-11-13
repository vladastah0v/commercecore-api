import asyncio
import os
from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.main as main
from app.core.config import Settings, get_settings
from app.core.tokens import create_access_token
from app.modules.catalog.models import Category, Product
from app.modules.users.models import User, UserRole

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)

SECRET = "test-only-secret-" * 3
URL = "/api/v1/products"


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


async def headers_for(session: AsyncSession, role: UserRole) -> dict[str, str]:
    user = User(
        email=f"{role.value}@example.com", password_hash="test", full_name="User", role=role
    )
    session.add(user)
    await session.commit()
    token = create_access_token(user.id, Settings(_env_file=None, jwt_secret=SECRET))
    return {"Authorization": f"Bearer {token}"}


async def category_for(session: AsyncSession, slug: str = "books") -> Category:
    category = Category(name=slug.title(), slug=slug)
    session.add(category)
    await session.commit()
    return category


async def test_admin_create_update_deactivate_and_reactivate(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    category = await category_for(db_session)
    headers = await headers_for(db_session, UserRole.ADMIN)
    payload = {
        "category_id": str(category.id),
        "name": "Book",
        "slug": "book",
        "price": "12.30",
        "stock_quantity": 3,
        "description": "Description",
    }
    created = await client.post(URL, json=payload, headers=headers)
    assert created.status_code == 201
    product_id = created.json()["id"]
    assert created.json()["price"] == "12.30"
    assert (await client.get(f"{URL}/{product_id}")).status_code == 200
    updated = await client.patch(
        f"{URL}/{product_id}", json={"price": "8.50", "description": None}, headers=headers
    )
    assert updated.status_code == 200
    assert updated.json()["price"] == "8.50" and updated.json()["description"] is None
    assert (await client.delete(f"{URL}/{product_id}", headers=headers)).status_code == 204
    assert (await client.get(f"{URL}/{product_id}")).status_code == 404
    assert (await client.get(URL)).json() == []
    assert (await client.delete(f"{URL}/{product_id}", headers=headers)).status_code == 204
    reactivated = await client.patch(
        f"{URL}/{product_id}", json={"is_active": True}, headers=headers
    )
    assert reactivated.status_code == 200
    assert (await client.get(f"{URL}/{product_id}")).status_code == 200


async def test_product_writes_require_admin(client: AsyncClient, db_session: AsyncSession) -> None:
    category = await category_for(db_session)
    product = Product(category_id=category.id, name="Book", slug="book", price=Decimal("1.00"))
    db_session.add(product)
    await db_session.commit()
    payload = {"category_id": str(category.id), "name": "Other", "slug": "other", "price": "1.00"}
    assert (await client.post(URL, json=payload)).status_code == 401
    assert (await client.patch(f"{URL}/{product.id}", json={"name": "Changed"})).status_code == 401
    assert (await client.delete(f"{URL}/{product.id}")).status_code == 401
    for role in (UserRole.CUSTOMER, UserRole.MANAGER):
        headers = await headers_for(db_session, role)
        assert (await client.post(URL, json=payload, headers=headers)).status_code == 403
        assert (
            await client.patch(f"{URL}/{product.id}", json={"name": "Changed"}, headers=headers)
        ).status_code == 403
        assert (await client.delete(f"{URL}/{product.id}", headers=headers)).status_code == 403
    assert (await client.get(f"{URL}/{product.id}")).status_code == 200


async def test_public_filters_pagination_sorting_and_search(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    books = await category_for(db_session, "books")
    music = await category_for(db_session, "music")
    db_session.add_all(
        [
            Product(category_id=books.id, name="Alpha Book", slug="alpha", price=Decimal("10.00")),
            Product(category_id=books.id, name="Beta Book", slug="beta", price=Decimal("20.00")),
            Product(category_id=books.id, name="100% Book", slug="percent", price=Decimal("30.00")),
            Product(
                category_id=books.id, name="100X Book", slug="hundred-x", price=Decimal("40.00")
            ),
            Product(category_id=music.id, name="Music", slug="music", price=Decimal("15.00")),
            Product(
                category_id=books.id,
                name="Hidden",
                slug="hidden",
                price=Decimal("1.00"),
                is_active=False,
            ),
        ]
    )
    await db_session.commit()
    response = await client.get(
        URL,
        params={
            "category_id": str(books.id),
            "search": "bOoK",
            "min_price": "10.00",
            "max_price": "30.00",
            "sort": "price_desc",
            "limit": 2,
            "offset": 1,
        },
    )
    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == ["Beta Book", "Alpha Book"]
    response = await client.get(URL, params={"search": "100%"})
    assert [item["name"] for item in response.json()] == ["100% Book"]
    response = await client.get(URL, params={"sort": "price_asc"})
    assert [item["price"] for item in response.json()] == [
        "10.00",
        "15.00",
        "20.00",
        "30.00",
        "40.00",
    ]
    assert (await client.get(URL, params={"limit": 101})).status_code == 422
    assert (await client.get(URL, params={"min_price": "20", "max_price": "10"})).status_code == 422
    assert (await client.get(URL, params={"sort": "invalid"})).status_code == 422
    assert (await client.get(URL, params={"offset": 2147483648})).status_code == 422


async def test_conflicts_invalid_inputs_and_missing_items(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    category = await category_for(db_session)
    headers = await headers_for(db_session, UserRole.ADMIN)
    payload = {"category_id": str(category.id), "name": "Book", "slug": "book", "price": "1.00"}
    first = await client.post(URL, json=payload, headers=headers)
    assert first.status_code == 201
    assert (await client.post(URL, json=payload, headers=headers)).status_code == 409
    second = await client.post(URL, json={**payload, "slug": "other"}, headers=headers)
    assert second.status_code == 201
    conflict = await client.patch(
        f"{URL}/{second.json()['id']}", json={"name": "Changed", "slug": "book"}, headers=headers
    )
    assert conflict.status_code == 409
    assert (await client.get(f"{URL}/{second.json()['id']}")).json()["name"] == "Book"
    assert (
        await client.post(
            URL, json={**payload, "slug": "other", "category_id": str(uuid4())}, headers=headers
        )
    ).status_code == 404
    assert (
        await client.post(URL, json={**payload, "slug": "other", "price": -1}, headers=headers)
    ).status_code == 422
    assert (
        await client.post(URL, json={**payload, "slug": "other", "price": 1.25}, headers=headers)
    ).status_code == 422
    assert (
        await client.patch(f"{URL}/{first.json()['id']}", json={}, headers=headers)
    ).status_code == 422
    assert (
        await client.patch(f"{URL}/{uuid4()}", json={"name": "Missing"}, headers=headers)
    ).status_code == 404
    assert (await client.delete(f"{URL}/{uuid4()}", headers=headers)).status_code == 404


async def test_concurrent_product_creation_rejects_duplicate_slug(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    category = await category_for(db_session)
    headers = await headers_for(db_session, UserRole.ADMIN)
    payload = {"category_id": str(category.id), "name": "Book", "slug": "book", "price": "1.00"}
    responses = await asyncio.gather(
        client.post(URL, json=payload, headers=headers),
        client.post(URL, json=payload, headers=headers),
    )
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert await db_session.scalar(select(func.count()).select_from(Product)) == 1
