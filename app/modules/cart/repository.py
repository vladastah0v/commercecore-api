from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cart.models import Cart, CartItem
from app.modules.catalog.models import Product


class CartRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create_locked(self, user_id: UUID) -> Cart:
        statement = (
            insert(Cart)
            .values(id=uuid4(), user_id=user_id)
            .on_conflict_do_nothing(index_elements=[Cart.user_id])
        )
        await self._session.execute(statement)
        cart = await self._session.scalar(
            select(Cart).where(Cart.user_id == user_id).with_for_update()
        )
        assert cart is not None
        return cart

    async def get_active_product_locked(self, product_id: UUID) -> Product | None:
        statement = select(Product).where(Product.id == product_id, Product.is_active.is_(True))
        return await self._session.scalar(statement.with_for_update(read=True))

    async def get_item(self, cart_id: UUID, product_id: UUID) -> CartItem | None:
        return await self._session.scalar(
            select(CartItem).where(CartItem.cart_id == cart_id, CartItem.product_id == product_id)
        )

    async def list_items(self, cart_id: UUID) -> list[tuple[CartItem, Product]]:
        statement = (
            select(CartItem, Product)
            .join(Product, Product.id == CartItem.product_id)
            .where(CartItem.cart_id == cart_id)
            .order_by(Product.name, Product.id)
        )
        return [(item, product) for item, product in (await self._session.execute(statement)).all()]

    async def add_item(self, item: CartItem) -> None:
        self._session.add(item)
        await self._session.flush()

    async def delete_item(self, item: CartItem) -> None:
        await self._session.delete(item)
        await self._session.flush()

    async def clear(self, cart_id: UUID) -> None:
        await self._session.execute(delete(CartItem).where(CartItem.cart_id == cart_id))

    async def touch(self, cart_id: UUID) -> None:
        await self._session.execute(
            update(Cart).where(Cart.id == cart_id).values(updated_at=func.now())
        )
