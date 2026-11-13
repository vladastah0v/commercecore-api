import asyncio
import os
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.cart.models import Cart, CartItem
from app.modules.catalog.models import Category, Product
from app.modules.orders.models import Order, OrderItem, OrderStatus
from app.modules.users.models import User

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)


async def create_store(session: AsyncSession) -> tuple[User, Category, Product]:
    user = User(email="customer@example.test", password_hash="test-hash", full_name="Customer")
    category = Category(name="Books", slug="books")
    session.add_all([user, category])
    await session.flush()
    product = Product(
        category_id=category.id,
        name="Book",
        slug="book",
        price=Decimal("12.30"),
        stock_quantity=5,
    )
    session.add(product)
    await session.flush()
    return user, category, product


async def test_product_money_defaults_and_category_protection(db_session: AsyncSession) -> None:
    _, category, product = await create_store(db_session)
    product_id = product.id
    db_session.expunge_all()

    saved = await db_session.get(Product, product_id)
    assert saved is not None
    assert isinstance(saved.id, UUID)
    assert saved.price == Decimal("12.30")
    assert isinstance(saved.price, Decimal)
    assert saved.stock_quantity == 5
    assert saved.is_active is True

    with pytest.raises(IntegrityError, match="fk_products_category_id_categories"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("DELETE FROM categories WHERE id = :id"), {"id": category.id}
            )


async def test_product_constraints(db_session: AsyncSession) -> None:
    _, category, product = await create_store(db_session)
    cases = [
        ("UPDATE products SET price = -0.01 WHERE id = :id", "ck_products_price_non_negative"),
        (
            "UPDATE products SET stock_quantity = -1 WHERE id = :id",
            "ck_products_stock_quantity_non_negative",
        ),
        ("UPDATE products SET category_id = :other WHERE id = :id", "fk_products_category_id"),
    ]
    for statement, constraint in cases:
        with pytest.raises(IntegrityError, match=constraint):
            async with db_session.begin_nested():
                await db_session.execute(text(statement), {"id": product.id, "other": uuid4()})

    with pytest.raises(IntegrityError, match="ix_products_slug"):
        async with db_session.begin_nested():
            db_session.add(
                Product(category_id=category.id, name="Other", slug="book", price=Decimal("0"))
            )
            await db_session.flush()


async def test_cart_uniqueness_quantity_and_cascade(db_session: AsyncSession) -> None:
    user, _, product = await create_store(db_session)
    cart = Cart(user_id=user.id)
    db_session.add(cart)
    await db_session.flush()
    item = CartItem(cart_id=cart.id, product_id=product.id, quantity=2)
    db_session.add(item)
    await db_session.flush()
    item_id = item.id

    with pytest.raises(IntegrityError, match="uq_carts_user_id"):
        async with db_session.begin_nested():
            db_session.add(Cart(user_id=user.id))
            await db_session.flush()

    with pytest.raises(IntegrityError, match="uq_cart_items_cart_id_product_id"):
        async with db_session.begin_nested():
            db_session.add(CartItem(cart_id=cart.id, product_id=product.id, quantity=1))
            await db_session.flush()

    for quantity in (0, -1):
        with pytest.raises(IntegrityError, match="ck_cart_items_quantity_positive"):
            async with db_session.begin_nested():
                await db_session.execute(
                    text("UPDATE cart_items SET quantity = :quantity WHERE id = :id"),
                    {"quantity": quantity, "id": item_id},
                )

    await db_session.delete(cart)
    await db_session.flush()
    db_session.expunge_all()
    assert await db_session.get(CartItem, item_id) is None
    assert await db_session.get(Product, product.id) is not None


async def test_cart_items_require_existing_cart_and_product(db_session: AsyncSession) -> None:
    user, _, product = await create_store(db_session)
    cart = Cart(user_id=user.id)
    db_session.add(cart)
    await db_session.flush()
    cases = [
        (uuid4(), product.id, "fk_cart_items_cart_id_carts"),
        (cart.id, uuid4(), "fk_cart_items_product_id_products"),
    ]
    for cart_id, product_id, constraint in cases:
        with pytest.raises(IntegrityError, match=constraint):
            async with db_session.begin_nested():
                db_session.add(CartItem(cart_id=cart_id, product_id=product_id, quantity=1))
                await db_session.flush()


async def test_orders_enforce_idempotency_per_user(db_session: AsyncSession) -> None:
    user, _, _ = await create_store(db_session)
    other = User(email="other@example.test", password_hash="hash", full_name="Other")
    db_session.add(other)
    await db_session.flush()
    order = Order(
        user_id=user.id, total_amount=Decimal("12.30"), idempotency_key="key", request_hash="a" * 64
    )
    db_session.add(order)
    await db_session.flush()
    assert order.status is OrderStatus.PENDING

    with pytest.raises(IntegrityError, match="uq_orders_user_id_idempotency_key"):
        async with db_session.begin_nested():
            db_session.add(
                Order(
                    user_id=user.id,
                    total_amount=Decimal("12.30"),
                    idempotency_key="key",
                    request_hash="b" * 64,
                )
            )
            await db_session.flush()

    db_session.add(
        Order(
            user_id=other.id,
            total_amount=Decimal("12.30"),
            idempotency_key="key",
            request_hash="c" * 64,
        )
    )
    await db_session.flush()


async def test_concurrent_orders_cannot_share_a_key_for_one_user(db_session: AsyncSession) -> None:
    user, _, _ = await create_store(db_session)
    user_id = user.id
    await db_session.commit()
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async with session_factory() as first, session_factory() as second:
        first_pid = await first.scalar(text("SELECT pg_backend_pid()"))
        second_pid = await second.scalar(text("SELECT pg_backend_pid()"))
        first.add(
            Order(
                user_id=user_id, total_amount=Decimal("0"), idempotency_key="same", request_hash="a"
            )
        )
        await first.flush()

        async def insert_second() -> None:
            second.add(
                Order(
                    user_id=user_id,
                    total_amount=Decimal("0"),
                    idempotency_key="same",
                    request_hash="b",
                )
            )
            await second.flush()

        second_task = asyncio.create_task(insert_second())
        try:
            async with asyncio.timeout(10):
                while True:
                    if second_task.done():
                        await second_task
                        raise AssertionError("The second insert did not wait for the first")
                    blockers = await db_session.scalar(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": second_pid}
                    )
                    if first_pid in blockers:
                        break
                    await asyncio.sleep(0.05)
            await first.commit()
            with pytest.raises(IntegrityError, match="uq_orders_user_id_idempotency_key"):
                await second_task
            await second.rollback()
        finally:
            if not second_task.done():
                second_task.cancel()
                await asyncio.gather(second_task, return_exceptions=True)

    count = await db_session.scalar(
        text("SELECT count(*) FROM orders WHERE user_id = :id AND idempotency_key = 'same'"),
        {"id": user_id},
    )
    assert count == 1


async def test_order_status_amount_and_required_key_constraints(db_session: AsyncSession) -> None:
    user, _, _ = await create_store(db_session)
    order = Order(
        user_id=user.id, total_amount=Decimal("0"), idempotency_key="key", request_hash="a"
    )
    db_session.add(order)
    await db_session.flush()
    for status in OrderStatus:
        order.status = status
        await db_session.flush()

    cases = [
        ("UPDATE orders SET status = 'invalid' WHERE id = :id", "ck_orders_order_status"),
        ("UPDATE orders SET total_amount = -0.01 WHERE id = :id", "ck_orders_total_amount"),
        ("UPDATE orders SET idempotency_key = '  ' WHERE id = :id", "ck_orders_idempotency_key"),
        ("UPDATE orders SET user_id = :other WHERE id = :id", "fk_orders_user_id_users"),
    ]
    for statement, constraint in cases:
        with pytest.raises(IntegrityError, match=constraint):
            async with db_session.begin_nested():
                await db_session.execute(text(statement), {"id": order.id, "other": uuid4()})


async def test_order_items_keep_snapshot_and_protect_product_history(
    db_session: AsyncSession,
) -> None:
    user, _, product = await create_store(db_session)
    order = Order(
        user_id=user.id, total_amount=Decimal("24.60"), idempotency_key="key", request_hash="a" * 64
    )
    db_session.add(order)
    await db_session.flush()
    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        product_name=product.name,
        quantity=2,
        unit_price=product.price,
        line_total=Decimal("24.60"),
    )
    db_session.add(item)
    await db_session.flush()
    item_id = item.id
    product.name = "Updated"
    product.price = Decimal("99.00")
    product.is_active = False
    await db_session.flush()
    db_session.expunge_all()
    saved = await db_session.get(OrderItem, item_id)
    assert saved is not None
    assert (saved.product_name, saved.unit_price, saved.line_total) == (
        "Book",
        Decimal("12.30"),
        Decimal("24.60"),
    )

    with pytest.raises(IntegrityError, match="fk_order_items_product_id_products"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("DELETE FROM products WHERE id = :id"), {"id": product.id}
            )

    cases = [
        ("quantity", 0, "ck_order_items_quantity_positive"),
        ("unit_price", Decimal("-0.01"), "ck_order_items_unit_price_non_negative"),
        ("line_total", Decimal("-0.01"), "ck_order_items_line_total_non_negative"),
    ]
    for column, value, constraint in cases:
        with pytest.raises(IntegrityError, match=constraint):
            async with db_session.begin_nested():
                await db_session.execute(
                    text(f"UPDATE order_items SET {column} = :value WHERE id = :id"),
                    {"value": value, "id": item_id},
                )


async def test_order_items_require_existing_order_and_product(db_session: AsyncSession) -> None:
    user, _, product = await create_store(db_session)
    order = Order(
        user_id=user.id, total_amount=Decimal("0"), idempotency_key="key", request_hash="a" * 64
    )
    db_session.add(order)
    await db_session.flush()
    cases = [
        (uuid4(), product.id, "fk_order_items_order_id_orders"),
        (order.id, uuid4(), "fk_order_items_product_id_products"),
    ]
    for order_id, product_id, constraint in cases:
        with pytest.raises(IntegrityError, match=constraint):
            async with db_session.begin_nested():
                db_session.add(
                    OrderItem(
                        order_id=order_id,
                        product_id=product_id,
                        product_name="Book",
                        quantity=1,
                        unit_price=Decimal("1.00"),
                        line_total=Decimal("1.00"),
                    )
                )
                await db_session.flush()


async def test_commerce_timestamps_use_timezone_aware_columns(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name IN ('products', 'carts', 'orders') "
            "AND column_name IN ('created_at', 'updated_at')"
        )
    )
    columns = {(table, column): data_type for table, column, data_type in result}
    assert columns == {
        (table, column): "timestamp with time zone"
        for table in ("products", "carts", "orders")
        for column in ("created_at", "updated_at")
    }
