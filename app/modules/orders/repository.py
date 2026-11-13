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
