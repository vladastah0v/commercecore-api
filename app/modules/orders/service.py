import json
from collections.abc import Sequence
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cart.models import CartItem
from app.modules.cart.repository import CartRepository
from app.modules.orders.exceptions import (
    CartChangedError,
    EmptyCartError,
    IdempotencyConflictError,
    InsufficientStockError,
    InvalidOrderTransitionError,
    OrderAmountLimitError,
    OrderNotFoundError,
    OrderProductUnavailableError,
    StockRestoreError,
)
from app.modules.orders.models import Order, OrderItem, OrderStatus
from app.modules.orders.repository import OrderRepository
from app.modules.orders.schemas import CheckoutItem, CheckoutRequest, OrderItemRead, OrderRead

MAX_AMOUNT = Decimal("9999999999.99")
MAX_STOCK = 2147483647
ALLOWED_TRANSITIONS = {
    OrderStatus.PENDING: frozenset({OrderStatus.CONFIRMED, OrderStatus.CANCELLED}),
    OrderStatus.CONFIRMED: frozenset({OrderStatus.COMPLETED, OrderStatus.CANCELLED}),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.COMPLETED: frozenset(),
}


def cart_fingerprint(items: Sequence[CartItem] | Sequence[CheckoutItem]) -> str:
    contents = sorted((str(item.product_id), item.quantity) for item in items)
    return sha256(json.dumps(contents, separators=(",", ":")).encode("utf-8")).hexdigest()


def order_response(order: Order, items: Sequence[OrderItem]) -> OrderRead:
    return OrderRead(
        id=order.id,
        status=order.status,
        total_amount=order.total_amount,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=[OrderItemRead.model_validate(item) for item in items],
    )


class CheckoutService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._orders = OrderRepository(session)
        self._carts = CartRepository(session)

    async def _response(self, order: Order) -> OrderRead:
        items = await self._orders.get_order_items(order.id)
        return order_response(order, items)

    async def checkout(
        self, user_id: UUID, key: str, data: CheckoutRequest
    ) -> tuple[OrderRead, bool]:
        request_hash = cart_fingerprint(data.items)
        try:
            cart = await self._carts.get_or_create_locked(user_id)
            existing = await self._orders.get_by_key(user_id, key)
            if existing is not None:
                if request_hash != existing.request_hash:
                    raise IdempotencyConflictError
                result = await self._response(existing)
                await self._session.commit()
                return result, False
            items = await self._orders.get_cart_items(cart.id)
            if not items:
                raise EmptyCartError
            if cart_fingerprint(items) != request_hash:
                raise CartChangedError
            products = await self._orders.lock_products([item.product_id for item in items])
            if len(products) != len(items) or any(not product.is_active for product in products):
                raise OrderProductUnavailableError
            by_id = {product.id: product for product in products}
            total = Decimal("0.00")
            for item in items:
                product = by_id[item.product_id]
                if product.stock_quantity < item.quantity:
                    raise InsufficientStockError
                total += product.price * item.quantity
                if total > MAX_AMOUNT:
                    raise OrderAmountLimitError

            order = Order(
                user_id=user_id, idempotency_key=key, request_hash=request_hash, total_amount=total
            )
            await self._orders.add_order(order)
            order_items = []
            for item in items:
                product = by_id[item.product_id]
                order_items.append(
                    OrderItem(
                        order_id=order.id,
                        product_id=product.id,
                        product_name=product.name,
                        quantity=item.quantity,
                        unit_price=product.price,
                        line_total=product.price * item.quantity,
                    )
                )
                product.stock_quantity -= item.quantity
            await self._orders.add_items(order_items)
            await self._carts.clear(cart.id)
            await self._carts.touch(cart.id)
            result = await self._response(order)
            await self._session.commit()
            return result, True
        except IntegrityError as error:
            await self._session.rollback()
            original = error.orig
            if (
                getattr(original, "sqlstate", None) == "23505"
                and getattr(original.__cause__, "constraint_name", None)
                == "uq_orders_user_id_idempotency_key"
            ):
                existing = await self._orders.get_by_key(user_id, key)
                if existing is not None and existing.request_hash == request_hash:
                    result = await self._response(existing)
                    await self._session.commit()
                    return result, False
                await self._session.rollback()
                raise IdempotencyConflictError from None
            raise
        except BaseException:
            await self._session.rollback()
            raise


class OrderService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._orders = OrderRepository(session)

    async def list_orders(self, user_id: UUID) -> list[OrderRead]:
        orders = await self._orders.list_by_user(user_id)
        items = await self._orders.get_items_for_orders([order.id for order in orders])
        grouped: dict[UUID, list[OrderItem]] = {order.id: [] for order in orders}
        for item in items:
            grouped[item.order_id].append(item)
        return [order_response(order, grouped[order.id]) for order in orders]

    async def get_order(self, user_id: UUID, order_id: UUID) -> OrderRead:
        order = await self._orders.get_by_id(order_id, user_id=user_id)
        if order is None:
            raise OrderNotFoundError
        return order_response(order, await self._orders.get_order_items(order.id))

    async def change_status(self, order_id: UUID, new_status: OrderStatus) -> OrderRead:
        try:
            order = await self._orders.get_by_id(order_id, lock=True)
            if order is None:
                raise OrderNotFoundError
            if new_status not in ALLOWED_TRANSITIONS[order.status]:
                raise InvalidOrderTransitionError
            items = await self._orders.get_order_items(order.id)
            if new_status == OrderStatus.CANCELLED:
                quantities: dict[UUID, int] = {}
                for item in items:
                    quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity
                products = await self._orders.lock_products(sorted(quantities))
                if len(products) != len(quantities) or any(
                    product.stock_quantity + quantities[product.id] > MAX_STOCK
                    for product in products
                ):
                    raise StockRestoreError
                for product in products:
                    product.stock_quantity += quantities[product.id]
            order.status = new_status
            await self._session.flush()
            await self._session.refresh(order)
            result = order_response(order, items)
            await self._session.commit()
            return result
        except BaseException:
            await self._session.rollback()
            raise
