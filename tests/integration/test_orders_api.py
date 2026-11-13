import asyncio
import os
from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

import app.main as main
import app.modules.orders.service as order_service
from app.core.config import Settings, get_settings
from app.core.tokens import create_access_token
from app.modules.catalog.models import Category, Product
from app.modules.orders.models import Order, OrderItem, OrderStatus
from app.modules.users.models import User, UserRole

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


def auth(user: User) -> dict[str, str]:
    token = create_access_token(user.id, Settings(_env_file=None, jwt_secret=SECRET))
    return {"Authorization": f"Bearer {token}"}


async def seed(session: AsyncSession) -> tuple[User, User, User, User, Product, Order]:
    owner = User(email="owner@example.com", password_hash="hash", full_name="Owner")
    other = User(email="other@example.com", password_hash="hash", full_name="Other")
    manager = User(
        email="manager@example.com",
        password_hash="hash",
        full_name="Manager",
        role=UserRole.MANAGER,
    )
    admin = User(
        email="admin@example.com", password_hash="hash", full_name="Admin", role=UserRole.ADMIN
    )
    category = Category(name="Books", slug="books")
    session.add_all([owner, other, manager, admin, category])
    await session.flush()
    product = Product(
        category_id=category.id, name="Book", slug="book", price=Decimal("12.30"), stock_quantity=4
    )
    session.add(product)
    await session.flush()
    order = Order(
        user_id=owner.id,
        total_amount=Decimal("12.30"),
        idempotency_key="key",
        request_hash="a" * 64,
    )
    session.add(order)
    await session.flush()
    session.add(
        OrderItem(
            order_id=order.id,
            product_id=product.id,
            product_name="Book",
            quantity=1,
            unit_price=Decimal("12.30"),
            line_total=Decimal("12.30"),
        )
    )
    await session.commit()
    return owner, other, manager, admin, product, order


async def test_order_list_and_detail_are_owned_and_batched(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner, other, _, _, product, order = await seed(db_session)
    second = Order(
        user_id=owner.id,
        total_amount=Decimal("12.30"),
        idempotency_key="key-2",
        request_hash="b" * 64,
    )
    db_session.add(second)
    await db_session.flush()
    db_session.add(
        OrderItem(
            order_id=second.id,
            product_id=product.id,
            product_name="Book",
            quantity=1,
            unit_price=Decimal("12.30"),
            line_total=Decimal("12.30"),
        )
    )
    await db_session.commit()
    selects: list[str] = []

    def record_select(conn, cursor, statement, parameters, context, executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(main.app.state.db_engine.sync_engine, "before_cursor_execute", record_select)
    try:
        listing = await client.get(URL, headers=auth(owner))
    finally:
        event.remove(main.app.state.db_engine.sync_engine, "before_cursor_execute", record_select)
    assert listing.status_code == 200
    assert {item["id"] for item in listing.json()} == {str(order.id), str(second.id)}
    assert all(len(item["items"]) == 1 for item in listing.json())
    assert len(selects) == 3
    detail = await client.get(f"{URL}/{order.id}", headers=auth(owner))
    assert detail.status_code == 200 and detail.json()["items"][0]["product_name"] == "Book"
    assert (await client.get(URL, headers=auth(other))).json() == []
    assert (await client.get(f"{URL}/{order.id}", headers=auth(other))).status_code == 404
    assert (await client.get(f"{URL}/{uuid4()}", headers=auth(owner))).status_code == 404
    assert (await client.get(URL)).status_code == 401


async def test_status_access_and_valid_transitions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner, _, manager, admin, product, order = await seed(db_session)
    endpoint = f"{URL}/{order.id}/status"
    assert (await client.patch(endpoint, json={"status": "confirmed"})).status_code == 401
    assert (
        await client.patch(endpoint, headers=auth(owner), json={"status": "confirmed"})
    ).status_code == 403
    assert (
        await client.patch(endpoint, headers=auth(manager), json={"status": "completed"})
    ).status_code == 409
    confirmed = await client.patch(endpoint, headers=auth(manager), json={"status": "confirmed"})
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"
    completed = await client.patch(endpoint, headers=auth(admin), json={"status": "completed"})
    assert completed.status_code == 200 and completed.json()["status"] == "completed"
    assert (
        await client.patch(endpoint, headers=auth(admin), json={"status": "cancelled"})
    ).status_code == 409
    assert (
        await client.patch(endpoint, headers=auth(admin), json={"status": "invalid"})
    ).status_code == 422
    assert (
        await client.patch(
            f"{URL}/{uuid4()}/status", headers=auth(admin), json={"status": "confirmed"}
        )
    ).status_code == 404
    await db_session.refresh(product)
    assert product.stock_quantity == 4


async def test_concurrent_cancellation_restores_stock_once_even_if_inactive(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, manager, _, product, order = await seed(db_session)
    product.is_active = False
    await db_session.commit()
    endpoint = f"{URL}/{order.id}/status"
    headers = auth(manager)
    assert (
        await client.patch(endpoint, headers=headers, json={"status": "confirmed"})
    ).status_code == 200
    responses = await asyncio.gather(
        client.patch(endpoint, headers=headers, json={"status": "cancelled"}),
        client.patch(endpoint, headers=headers, json={"status": "cancelled"}),
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    await db_session.refresh(product)
    await db_session.refresh(order)
    assert product.stock_quantity == 5
    assert order.status is OrderStatus.CANCELLED
    assert (
        await client.patch(endpoint, headers=headers, json={"status": "cancelled"})
    ).status_code == 409
    await db_session.refresh(product)
    assert product.stock_quantity == 5


async def test_concurrent_cancellation_of_different_orders_preserves_both_restocks(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner, _, manager, _, product, first = await seed(db_session)
    second = Order(
        user_id=owner.id,
        total_amount=Decimal("12.30"),
        idempotency_key="second-key",
        request_hash="b" * 64,
    )
    db_session.add(second)
    await db_session.flush()
    db_session.add(
        OrderItem(
            order_id=second.id,
            product_id=product.id,
            product_name="Book",
            quantity=1,
            unit_price=Decimal("12.30"),
            line_total=Decimal("12.30"),
        )
    )
    await db_session.commit()
    headers = auth(manager)
    responses = await asyncio.gather(
        client.patch(f"{URL}/{first.id}/status", headers=headers, json={"status": "cancelled"}),
        client.patch(f"{URL}/{second.id}/status", headers=headers, json={"status": "cancelled"}),
    )
    assert [response.status_code for response in responses] == [200, 200]
    await db_session.refresh(product)
    assert product.stock_quantity == 6


async def test_stock_overflow_rolls_back_cancellation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, manager, _, product, order = await seed(db_session)
    product.stock_quantity = 2147483647
    await db_session.commit()
    response = await client.patch(
        f"{URL}/{order.id}/status", headers=auth(manager), json={"status": "cancelled"}
    )
    assert response.status_code == 409
    await db_session.refresh(order)
    await db_session.refresh(product)
    assert order.status is OrderStatus.PENDING
    assert product.stock_quantity == 2147483647


async def test_failure_during_cancellation_rolls_back_stock_and_status(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    _, _, manager, _, product, order = await seed(db_session)

    def fail_response(order, items):
        raise SQLAlchemyError("sensitive failure")

    with monkeypatch.context() as patch:
        patch.setattr(order_service, "order_response", fail_response)
        response = await client.patch(
            f"{URL}/{order.id}/status", headers=auth(manager), json={"status": "cancelled"}
        )
    assert response.status_code == 500
    assert "sensitive failure" not in response.text
    await db_session.refresh(order)
    await db_session.refresh(product)
    assert order.status is OrderStatus.PENDING
    assert product.stock_quantity == 4
    assert (
        await client.patch(
            f"{URL}/{order.id}/status", headers=auth(manager), json={"status": "cancelled"}
        )
    ).status_code == 200
