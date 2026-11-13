from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cart.exceptions import CartItemNotFoundError, CartQuantityLimitError
from app.modules.cart.models import Cart, CartItem
from app.modules.cart.repository import CartRepository
from app.modules.cart.schemas import CartItemRead, CartRead
from app.modules.catalog.exceptions import ProductNotFoundError

MAX_QUANTITY = 2147483647


class CartService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._carts = CartRepository(session)

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        try:
            yield
            await self._session.commit()
        except BaseException:
            await self._session.rollback()
            raise

    async def _snapshot(self, cart: Cart) -> CartRead:
        items = await self._carts.list_items(cart.id)
        return CartRead(
            id=cart.id,
            items=[
                CartItemRead(
                    product_id=product.id,
                    name=product.name,
                    price=product.price,
                    is_active=product.is_active,
                    quantity=item.quantity,
                )
                for item, product in items
            ],
        )

    async def get_cart(self, user_id: UUID) -> CartRead:
        async with self._transaction():
            cart = await self._carts.get_or_create_locked(user_id)
            result = await self._snapshot(cart)
        return result

    async def add_item(self, user_id: UUID, product_id: UUID, quantity: int) -> CartRead:
        async with self._transaction():
            cart = await self._carts.get_or_create_locked(user_id)
            if await self._carts.get_active_product_locked(product_id) is None:
                raise ProductNotFoundError
            item = await self._carts.get_item(cart.id, product_id)
            if item is None:
                await self._carts.add_item(
                    CartItem(cart_id=cart.id, product_id=product_id, quantity=quantity)
                )
            else:
                if item.quantity + quantity > MAX_QUANTITY:
                    raise CartQuantityLimitError
                item.quantity += quantity
                await self._session.flush()
            await self._carts.touch(cart.id)
            result = await self._snapshot(cart)
        return result

    async def update_item(self, user_id: UUID, product_id: UUID, quantity: int) -> CartRead:
        async with self._transaction():
            cart = await self._carts.get_or_create_locked(user_id)
            item = await self._carts.get_item(cart.id, product_id)
            if item is None:
                raise CartItemNotFoundError
            if await self._carts.get_active_product_locked(product_id) is None:
                raise ProductNotFoundError
            item.quantity = quantity
            await self._session.flush()
            await self._carts.touch(cart.id)
            result = await self._snapshot(cart)
        return result

    async def delete_item(self, user_id: UUID, product_id: UUID) -> None:
        async with self._transaction():
            cart = await self._carts.get_or_create_locked(user_id)
            item = await self._carts.get_item(cart.id, product_id)
            if item is None:
                raise CartItemNotFoundError
            await self._carts.delete_item(item)
            await self._carts.touch(cart.id)

    async def clear(self, user_id: UUID) -> None:
        async with self._transaction():
            cart = await self._carts.get_or_create_locked(user_id)
            await self._carts.clear(cart.id)
            await self._carts.touch(cart.id)
