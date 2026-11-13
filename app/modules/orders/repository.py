from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cart.models import CartItem
from app.modules.catalog.models import Product
from app.modules.orders.models import Order, OrderItem


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_key(self, user_id: UUID, key: str) -> Order | None:
        return await self._session.scalar(
            select(Order).where(Order.user_id == user_id, Order.idempotency_key == key)
        )

    async def list_by_user(self, user_id: UUID) -> list[Order]:
        statement = (
            select(Order)
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc(), Order.id.desc())
        )
        return list((await self._session.scalars(statement)).all())

    async def get_by_id(
        self, order_id: UUID, *, user_id: UUID | None = None, lock: bool = False
    ) -> Order | None:
        statement = select(Order).where(Order.id == order_id)
        if user_id is not None:
            statement = statement.where(Order.user_id == user_id)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return await self._session.scalar(statement)

    async def get_cart_items(self, cart_id: UUID) -> list[CartItem]:
        statement = (
            select(CartItem).where(CartItem.cart_id == cart_id).order_by(CartItem.product_id)
        )
        return list((await self._session.scalars(statement)).all())

    async def lock_products(self, product_ids: list[UUID]) -> list[Product]:
        statement = (
            select(Product)
            .where(Product.id.in_(product_ids))
            .order_by(Product.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list((await self._session.scalars(statement)).all())

    async def add_order(self, order: Order) -> None:
        self._session.add(order)
        await self._session.flush()

    async def add_items(self, items: list[OrderItem]) -> None:
        self._session.add_all(items)
        await self._session.flush()

    async def get_order_items(self, order_id: UUID) -> list[OrderItem]:
        statement = (
            select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.product_id)
        )
        return list((await self._session.scalars(statement)).all())

    async def get_items_for_orders(self, order_ids: list[UUID]) -> list[OrderItem]:
        if not order_ids:
            return []
        statement = (
            select(OrderItem)
            .where(OrderItem.order_id.in_(order_ids))
            .order_by(OrderItem.order_id, OrderItem.product_id)
        )
        return list((await self._session.scalars(statement)).all())
