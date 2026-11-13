from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.dependencies import get_current_user, require_roles
from app.modules.orders.schemas import CheckoutRequest, OrderRead, OrderStatusUpdate
from app.modules.orders.service import CheckoutService, OrderService
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/orders", tags=["orders"])


def get_checkout_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CheckoutService:
    return CheckoutService(session)


def get_order_service(session: Annotated[AsyncSession, Depends(get_db_session)]) -> OrderService:
    return OrderService(session)


@router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def checkout(
    response: Response,
    data: CheckoutRequest,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[CheckoutService, Depends(get_checkout_service)],
    key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=255, pattern=r".*\S.*")
    ],
) -> OrderRead:
    result, created = await service.checkout(user.id, key, data)
    if not created:
        response.status_code = status.HTTP_200_OK
    return result


@router.get("", response_model=list[OrderRead])
async def list_orders(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OrderService, Depends(get_order_service)],
) -> list[OrderRead]:
    return await service.list_orders(user.id)


@router.get("/{order_id}", response_model=OrderRead)
async def get_order(
    order_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OrderService, Depends(get_order_service)],
) -> OrderRead:
    return await service.get_order(user.id, order_id)


@router.patch("/{order_id}/status", response_model=OrderRead)
async def change_order_status(
    order_id: UUID,
    data: OrderStatusUpdate,
    staff: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER))],
    service: Annotated[OrderService, Depends(get_order_service)],
) -> OrderRead:
    return await service.change_status(order_id, data.status)
