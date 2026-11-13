import asyncio
import os
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.main as main
from app.core.config import Settings, get_settings
from app.core.tokens import create_access_token
from app.modules.cart.repository import CartRepository
from app.modules.catalog.models import Category, Product
from app.modules.orders.models import Order
from app.modules.orders.repository import OrderRepository
from app.modules.users.models import User

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)
SECRET = "test-only-secret-" * 3
URL = "/api/v1/orders"


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


async def headers_for(
    session: AsyncSession, email: str = "user@example.com", key: str = "key"
) -> dict[str, str]:
    user = User(email=email, password_hash="test-hash", full_name="User")
    session.add(user)
    await session.commit()
    token = create_access_token(user.id, Settings(_env_file=None, jwt_secret=SECRET))
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": key}


async def make_products(session: AsyncSession, stock: int = 5) -> tuple[Product, Product]:
    category = Category(name="Books", slug="books")
    session.add(category)
    await session.flush()
    first = Product(
        category_id=category.id,
        name="Book",
        slug="book",
        price=Decimal("12.30"),
        stock_quantity=stock,
    )
    second = Product(
        category_id=category.id,
        name="Other",
        slug="other",
        price=Decimal("5.00"),
        stock_quantity=stock,
    )
    session.add_all([first, second])
    await session.commit()
    return first, second


async def add(
    client: AsyncClient, headers: dict[str, str], product: Product, quantity: int
) -> None:
    response = await client.post(
        "/api/v1/cart/items",
        headers=headers,
        json={"product_id": str(product.id), "quantity": quantity},
    )
    assert response.status_code == 200


def checkout_items(*items: tuple[Product, int]) -> dict:
    return {
        "items": [
            {"product_id": str(product.id), "quantity": quantity} for product, quantity in items
        ]
    }


async def test_checkout_is_atomic_and_replay_returns_original_snapshot(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first, second = await make_products(db_session)
    headers = await headers_for(db_session)
    await add(client, headers, first, 2)
    await add(client, headers, second, 1)
    response = await client.post(URL, headers=headers, json=checkout_items((first, 2), (second, 1)))
    assert response.status_code == 201
    original = response.json()
    assert original["status"] == "pending"
    assert original["total_amount"] == "29.60"
    items = {item["product_name"]: item for item in original["items"]}
    assert items["Book"]["quantity"] == 2
    assert items["Book"]["unit_price"] == "12.30"
    assert items["Book"]["line_total"] == "24.60"
    assert (await client.get("/api/v1/cart", headers=headers)).json()["items"] == []
    await db_session.refresh(first)
    await db_session.refresh(second)
    assert first.stock_quantity == 3 and second.stock_quantity == 4
    first.name = "Renamed"
    first.price = Decimal("99.00")
    await db_session.commit()
    replay = await client.post(URL, headers=headers, json=checkout_items((second, 1), (first, 2)))
    assert replay.status_code == 200 and replay.json() == original
    await db_session.refresh(first)
    assert first.stock_quantity == 3
    assert await db_session.scalar(select(func.count()).select_from(Order)) == 1


async def test_key_conflicts_with_changed_cart_and_preserves_cart(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first, _ = await make_products(db_session)
    headers = await headers_for(db_session)
    await add(client, headers, first, 1)
    original = await client.post(URL, headers=headers, json=checkout_items((first, 1)))
    assert original.status_code == 201
    assert (
        await client.post(URL, headers=headers, json=checkout_items((first, 2)))
    ).status_code == 409
    await add(client, headers, first, 2)
    response = await client.post(URL, headers=headers, json=checkout_items((first, 2)))
    assert response.status_code == 409
    replay = await client.post(URL, headers=headers, json=checkout_items((first, 1)))
    assert replay.status_code == 200 and replay.json() == original.json()
    assert (await client.get("/api/v1/cart", headers=headers)).json()["items"][0]["quantity"] == 2
    await db_session.refresh(first)
    assert first.stock_quantity == 4


async def test_first_request_must_match_current_cart(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first, _ = await make_products(db_session)
    headers = await headers_for(db_session)
    await add(client, headers, first, 2)
    response = await client.post(URL, headers=headers, json=checkout_items((first, 1)))
    assert response.status_code == 409
    assert await db_session.scalar(select(func.count()).select_from(Order)) == 0
    assert (await client.get("/api/v1/cart", headers=headers)).json()["items"][0]["quantity"] == 2
    await db_session.refresh(first)
    assert first.stock_quantity == 5


async def test_replay_with_same_refilled_cart_does_not_consume_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first, _ = await make_products(db_session)
    headers = await headers_for(db_session)
    await add(client, headers, first, 1)
    original = await client.post(URL, headers=headers, json=checkout_items((first, 1)))
    assert original.status_code == 201
    await add(client, headers, first, 1)
    replay = await client.post(URL, headers=headers, json=checkout_items((first, 1)))
    assert replay.status_code == 200 and replay.json() == original.json()
    assert (await client.get("/api/v1/cart", headers=headers)).json()["items"][0]["quantity"] == 1
    await db_session.refresh(first)
    assert first.stock_quantity == 4


async def test_insufficient_stock_rolls_back_all_changes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first, second = await make_products(db_session, stock=1)
    headers = await headers_for(db_session)
    await add(client, headers, first, 1)
    await add(client, headers, second, 2)
    response = await client.post(URL, headers=headers, json=checkout_items((first, 1), (second, 2)))
    assert response.status_code == 409
    assert len((await client.get("/api/v1/cart", headers=headers)).json()["items"]) == 2
    await db_session.refresh(first)
    await db_session.refresh(second)
    assert first.stock_quantity == second.stock_quantity == 1
    assert await db_session.scalar(select(func.count()).select_from(Order)) == 0


async def test_inactive_product_and_amount_overflow_are_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first, _ = await make_products(db_session, stock=2)
    headers = await headers_for(db_session)
    await add(client, headers, first, 2)
    first.is_active = False
    await db_session.commit()
    assert (
        await client.post(URL, headers=headers, json=checkout_items((first, 2)))
    ).status_code == 409
    first.is_active = True
    first.price = Decimal("9999999999.99")
    await db_session.commit()
    assert (
        await client.post(URL, headers=headers, json=checkout_items((first, 2)))
    ).status_code == 409
    await db_session.refresh(first)
    assert first.stock_quantity == 2
    assert len((await client.get("/api/v1/cart", headers=headers)).json()["items"]) == 1


async def test_same_key_concurrent_requests_create_one_order(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first, _ = await make_products(db_session, stock=1)
    headers = await headers_for(db_session)
    await add(client, headers, first, 1)
    responses = await asyncio.gather(
        client.post(URL, headers=headers, json=checkout_items((first, 1))),
        client.post(URL, headers=headers, json=checkout_items((first, 1))),
    )
    assert sorted(response.status_code for response in responses) == [200, 201]
    assert responses[0].json() == responses[1].json()
    await db_session.refresh(first)
    assert first.stock_quantity == 0
    assert await db_session.scalar(select(func.count()).select_from(Order)) == 1


async def test_concurrent_customers_cannot_oversell(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first, _ = await make_products(db_session, stock=1)
    alice = await headers_for(db_session, "alice@example.com", "same-key")
    bob = await headers_for(db_session, "bob@example.com", "same-key")
    await add(client, alice, first, 1)
    await add(client, bob, first, 1)
    responses = await asyncio.gather(
        client.post(URL, headers=alice, json=checkout_items((first, 1))),
        client.post(URL, headers=bob, json=checkout_items((first, 1))),
    )
    assert sorted(response.status_code for response in responses) == [201, 409]
    await db_session.refresh(first)
    assert first.stock_quantity == 0
    assert await db_session.scalar(select(func.count()).select_from(Order)) == 1
    loser = alice if responses[0].status_code == 409 else bob
    assert (await client.get("/api/v1/cart", headers=loser)).json()["items"][0]["quantity"] == 1


async def test_same_key_is_independent_for_different_users(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first, _ = await make_products(db_session, stock=2)
    alice = await headers_for(db_session, "alice@example.com", "same-key")
    bob = await headers_for(db_session, "bob@example.com", "same-key")
    await add(client, alice, first, 1)
    await add(client, bob, first, 1)
    responses = await asyncio.gather(
        client.post(URL, headers=alice, json=checkout_items((first, 1))),
        client.post(URL, headers=bob, json=checkout_items((first, 1))),
    )
    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json()["id"] != responses[1].json()["id"]
    await db_session.refresh(first)
    assert first.stock_quantity == 0


async def test_opposite_cart_orders_do_not_deadlock_or_oversell(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first, second = await make_products(db_session, stock=1)
    alice = await headers_for(db_session, "alice@example.com", "alice-key")
    bob = await headers_for(db_session, "bob@example.com", "bob-key")
    await add(client, alice, first, 1)
    await add(client, alice, second, 1)
    await add(client, bob, second, 1)
    await add(client, bob, first, 1)
    responses = await asyncio.wait_for(
        asyncio.gather(
            client.post(URL, headers=alice, json=checkout_items((first, 1), (second, 1))),
            client.post(URL, headers=bob, json=checkout_items((second, 1), (first, 1))),
        ),
        timeout=10,
    )
    assert sorted(response.status_code for response in responses) == [201, 409]
    await db_session.refresh(first)
    await db_session.refresh(second)
    assert first.stock_quantity == second.stock_quantity == 0


async def test_product_deactivated_before_lock_is_not_ordered(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    first, _ = await make_products(db_session)
    headers = await headers_for(db_session)
    await add(client, headers, first, 1)
    reached_lock = asyncio.Event()
    continue_lock = asyncio.Event()
    original_lock = OrderRepository.lock_products

    async def wait_before_lock(repository: OrderRepository, product_ids):
        reached_lock.set()
        await continue_lock.wait()
        return await original_lock(repository, product_ids)

    monkeypatch.setattr(OrderRepository, "lock_products", wait_before_lock)
    checkout = asyncio.create_task(
        client.post(URL, headers=headers, json=checkout_items((first, 1)))
    )
    try:
        await asyncio.wait_for(reached_lock.wait(), timeout=10)
        first.is_active = False
        await db_session.commit()
    finally:
        continue_lock.set()
    response = await asyncio.wait_for(checkout, timeout=10)
    assert response.status_code == 409
    await db_session.refresh(first)
    assert first.stock_quantity == 5
    assert len((await client.get("/api/v1/cart", headers=headers)).json()["items"]) == 1


async def test_price_changed_before_product_lock_is_used(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    first, _ = await make_products(db_session)
    headers = await headers_for(db_session)
    await add(client, headers, first, 1)
    reached_lock = asyncio.Event()
    continue_lock = asyncio.Event()
    original_lock = OrderRepository.lock_products

    async def wait_before_lock(repository: OrderRepository, product_ids):
        reached_lock.set()
        await continue_lock.wait()
        return await original_lock(repository, product_ids)

    monkeypatch.setattr(OrderRepository, "lock_products", wait_before_lock)
    checkout = asyncio.create_task(
        client.post(URL, headers=headers, json=checkout_items((first, 1)))
    )
    try:
        await asyncio.wait_for(reached_lock.wait(), timeout=10)
        first.price = Decimal("15.50")
        await db_session.commit()
    finally:
        continue_lock.set()
    response = await asyncio.wait_for(checkout, timeout=10)
    assert response.status_code == 201
    assert response.json()["total_amount"] == "15.50"
    assert response.json()["items"][0]["unit_price"] == "15.50"


async def test_required_key_and_empty_cart(client: AsyncClient, db_session: AsyncSession) -> None:
    first, _ = await make_products(db_session)
    headers = await headers_for(db_session)
    data = checkout_items((first, 1))
    assert (
        await client.post(URL, headers={"Idempotency-Key": "key"}, json=data)
    ).status_code == 401
    assert (
        await client.post(URL, headers={"Authorization": headers["Authorization"]}, json=data)
    ).status_code == 422
    assert (
        await client.post(URL, headers={**headers, "Idempotency-Key": "   "}, json=data)
    ).status_code == 422
    assert (
        await client.post(URL, headers=headers, json={"unexpected": "value"})
    ).status_code == 422
    assert (await client.post(URL, headers=headers)).status_code == 422
    duplicate_items = {"items": [data["items"][0], data["items"][0]]}
    assert (await client.post(URL, headers=headers, json=duplicate_items)).status_code == 422
    assert (await client.post(URL, headers=headers, json=data)).status_code == 400


async def test_unique_constraint_recovery_returns_existing_order(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    first, _ = await make_products(db_session)
    headers = await headers_for(db_session)
    await add(client, headers, first, 1)
    original = await client.post(URL, headers=headers, json=checkout_items((first, 1)))
    assert original.status_code == 201
    await add(client, headers, first, 1)
    real_get = OrderRepository.get_by_key
    calls = 0

    async def hide_first_read(repository: OrderRepository, user_id, key):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return await real_get(repository, user_id, key)

    monkeypatch.setattr(OrderRepository, "get_by_key", hide_first_read)
    replay = await client.post(URL, headers=headers, json=checkout_items((first, 1)))
    assert replay.status_code == 200 and replay.json() == original.json()
    assert (await client.get("/api/v1/cart", headers=headers)).json()["items"][0]["quantity"] == 1
    await db_session.refresh(first)
    assert first.stock_quantity == 4


async def test_failure_after_item_creation_rolls_back_order_and_stock(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    first, _ = await make_products(db_session)
    headers = await headers_for(db_session)
    await add(client, headers, first, 1)

    async def fail_clear(repository: CartRepository, cart_id) -> None:
        raise IntegrityError("sensitive SQL", {}, Exception("db failure"))

    with monkeypatch.context() as patch:
        patch.setattr(CartRepository, "clear", fail_clear)
        response = await client.post(URL, headers=headers, json=checkout_items((first, 1)))
    assert response.status_code == 500
    assert "sensitive SQL" not in response.text
    await db_session.refresh(first)
    assert first.stock_quantity == 5
    assert await db_session.scalar(select(func.count()).select_from(Order)) == 0
    assert (await client.get("/api/v1/cart", headers=headers)).json()["items"][0]["quantity"] == 1
    assert (
        await client.post(URL, headers=headers, json=checkout_items((first, 1)))
    ).status_code == 201
