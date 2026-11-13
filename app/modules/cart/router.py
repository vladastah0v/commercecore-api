from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.dependencies import get_current_user
from app.modules.cart.schemas import AddCartItem, CartRead, UpdateCartItem
from app.modules.cart.service import CartService
from app.modules.users.models import User

router = APIRouter(prefix="/cart", tags=["cart"])


def get_cart_service(session: Annotated[AsyncSession, Depends(get_db_session)]) -> CartService:
    return CartService(session)


@router.get("", response_model=CartRead)
async def get_cart(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[CartService, Depends(get_cart_service)],
) -> CartRead:
    return await service.get_cart(user.id)


@router.post("/items", response_model=CartRead)
async def add_item(
    data: AddCartItem,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[CartService, Depends(get_cart_service)],
) -> CartRead:
    return await service.add_item(user.id, data.product_id, data.quantity)


@router.patch("/items/{product_id}", response_model=CartRead)
async def update_item(
    product_id: UUID,
    data: UpdateCartItem,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[CartService, Depends(get_cart_service)],
) -> CartRead:
    return await service.update_item(user.id, product_id, data.quantity)


@router.delete("/items/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    product_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[CartService, Depends(get_cart_service)],
) -> Response:
    await service.delete_item(user.id, product_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_cart(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[CartService, Depends(get_cart_service)],
) -> Response:
    await service.clear(user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
