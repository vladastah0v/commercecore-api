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
from app.modules.cart.models import Cart, CartItem
from app.modules.catalog.models import Category, Product
from app.modules.users.models import User

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)

SECRET = "test-only-secret-" * 3
URL = "/api/v1/cart"


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


async def user_headers(session: AsyncSession, email: str = "user@example.com") -> dict[str, str]:
    user = User(email=email, password_hash="test-hash", full_name="User")
    session.add(user)
    await session.commit()
    token = create_access_token(user.id, Settings(_env_file=None, jwt_secret=SECRET))
    return {"Authorization": f"Bearer {token}"}


async def make_products(session: AsyncSession) -> tuple[Product, Product]:
    category = Category(name="Books", slug="books")
    session.add(category)
    await session.flush()
    first = Product(
        category_id=category.id, name="Book", slug="book", price=Decimal("12.30"), stock_quantity=0
    )
    second = Product(
        category_id=category.id, name="Other", slug="other", price=Decimal("5.00"), stock_quantity=5
    )
    session.add_all([first, second])
    await session.commit()
    return first, second


async def test_cart_full_flow_does_not_reserve_stock(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    product, other = await make_products(db_session)
    headers = await user_headers(db_session)
    empty = await client.get(URL, headers=headers)
    assert empty.status_code == 200 and empty.json()["items"] == []
    product_id = str(product.id)
    added = await client.post(
        f"{URL}/items", headers=headers, json={"product_id": product_id, "quantity": 2}
    )
    assert added.status_code == 200
    assert added.json()["items"] == [
        {
            "product_id": product_id,
            "name": "Book",
            "price": "12.30",
            "is_active": True,
            "quantity": 2,
        }
    ]
    repeated = await client.post(
        f"{URL}/items", headers=headers, json={"product_id": product_id, "quantity": 3}
    )
    assert repeated.json()["items"][0]["quantity"] == 5
    changed = await client.patch(f"{URL}/items/{product_id}", headers=headers, json={"quantity": 4})
    assert changed.status_code == 200 and changed.json()["items"][0]["quantity"] == 4
    assert (
        await client.post(
            f"{URL}/items", headers=headers, json={"product_id": str(other.id), "quantity": 1}
        )
    ).status_code == 200
    assert (await client.delete(f"{URL}/items/{other.id}", headers=headers)).status_code == 204
    assert len((await client.get(URL, headers=headers)).json()["items"]) == 1
    assert (await client.delete(URL, headers=headers)).status_code == 204
    assert (await client.get(URL, headers=headers)).json()["items"] == []
    await db_session.refresh(product)
    assert product.stock_quantity == 0


async def test_carts_are_isolated_by_authenticated_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first, second = await make_products(db_session)
    alice = await user_headers(db_session, "alice@example.com")
    bob = await user_headers(db_session, "bob@example.com")
    assert (
        await client.post(
            f"{URL}/items", headers=alice, json={"product_id": str(first.id), "quantity": 2}
        )
    ).status_code == 200
    assert (
        await client.post(
            f"{URL}/items", headers=bob, json={"product_id": str(second.id), "quantity": 3}
        )
    ).status_code == 200
    assert (await client.delete(f"{URL}/items/{first.id}", headers=bob)).status_code == 404
    assert (await client.delete(URL, headers=bob)).status_code == 204
    assert (await client.get(URL, headers=bob)).json()["items"] == []
    assert (await client.get(URL, headers=alice)).json()["items"][0]["quantity"] == 2
    assert (
        await client.post(
            f"{URL}/items",
            headers=bob,
            json={"product_id": str(first.id), "quantity": 1, "user_id": str(uuid4())},
        )
    ).status_code == 422


async def test_inactive_or_missing_products_cannot_be_added_or_updated(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    product, _ = await make_products(db_session)
    headers = await user_headers(db_session)
    assert (
        await client.post(
            f"{URL}/items", headers=headers, json={"product_id": str(product.id), "quantity": 1}
        )
    ).status_code == 200
    product.is_active = False
    await db_session.commit()
    for product_id in (str(product.id), str(uuid4())):
        assert (
            await client.post(
                f"{URL}/items", headers=headers, json={"product_id": product_id, "quantity": 1}
            )
        ).status_code == 404
    assert (
        await client.patch(f"{URL}/items/{product.id}", headers=headers, json={"quantity": 2})
    ).status_code == 404
    assert (await client.get(URL, headers=headers)).json()["items"][0]["is_active"] is False
    assert (await client.delete(f"{URL}/items/{product.id}", headers=headers)).status_code == 204


async def test_concurrent_adds_preserve_every_quantity(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    product, _ = await make_products(db_session)
    headers = await user_headers(db_session)
    payload = {"product_id": str(product.id), "quantity": 1}
    responses = await asyncio.gather(
        *(client.post(f"{URL}/items", headers=headers, json=payload) for _ in range(8))
    )
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()["id"] for response in responses}) == 1
    assert (await client.get(URL, headers=headers)).json()["items"][0]["quantity"] == 8
    assert await db_session.scalar(select(func.count()).select_from(Cart)) == 1
    assert await db_session.scalar(select(func.count()).select_from(CartItem)) == 1
    await db_session.refresh(product)
    assert product.stock_quantity == 0


async def test_concurrent_clear_and_add_are_serialized(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    product, _ = await make_products(db_session)
    headers = await user_headers(db_session)
    payload = {"product_id": str(product.id), "quantity": 1}
    assert (await client.post(f"{URL}/items", headers=headers, json=payload)).status_code == 200
    cleared, added = await asyncio.gather(
        client.delete(URL, headers=headers),
        client.post(f"{URL}/items", headers=headers, json=payload),
    )
    assert cleared.status_code == 204 and added.status_code == 200
    items = (await client.get(URL, headers=headers)).json()["items"]
    assert not items or (len(items) == 1 and items[0]["quantity"] == 1)


async def test_cart_validation_missing_items_and_quantity_overflow(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    product, _ = await make_products(db_session)
    headers = await user_headers(db_session)
    assert (await client.get(URL)).status_code == 401
    assert (
        await client.post(f"{URL}/items", json={"product_id": str(product.id), "quantity": 1})
    ).status_code == 401
    for quantity in (0, -1, 1.5, True, 2147483648):
        assert (
            await client.post(
                f"{URL}/items",
                headers=headers,
                json={"product_id": str(product.id), "quantity": quantity},
            )
        ).status_code == 422
    assert (
        await client.patch(f"{URL}/items/{product.id}", headers=headers, json={"quantity": 1})
    ).status_code == 404
    assert (await client.delete(f"{URL}/items/{product.id}", headers=headers)).status_code == 404
    assert (
        await client.post(
            f"{URL}/items",
            headers=headers,
            json={"product_id": str(product.id), "quantity": 2147483647},
        )
    ).status_code == 200
    assert (
        await client.post(
            f"{URL}/items", headers=headers, json={"product_id": str(product.id), "quantity": 1}
        )
    ).status_code == 422
    assert (await client.get(URL, headers=headers)).json()["items"][0]["quantity"] == 2147483647
