from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.dependencies import require_roles
from app.modules.catalog.models import Product
from app.modules.catalog.products_service import ProductService
from app.modules.catalog.schemas import ProductCreate, ProductFilters, ProductRead, ProductUpdate
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/products", tags=["products"])


def get_product_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ProductService:
    return ProductService(session)


@router.get("", response_model=list[ProductRead])
async def list_products(
    filters: Annotated[ProductFilters, Query()],
    service: Annotated[ProductService, Depends(get_product_service)],
) -> list[Product]:
    return await service.list_products(filters)


@router.get(
    "/{product_id}",
    response_model=ProductRead,
    responses={404: {"description": "Product not found"}},
)
async def get_product(
    product_id: UUID,
    service: Annotated[ProductService, Depends(get_product_service)],
) -> Product:
    return await service.get_product(product_id)


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(
    data: ProductCreate,
    admin: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    service: Annotated[ProductService, Depends(get_product_service)],
) -> Product:
    return await service.create_product(data)


@router.patch("/{product_id}", response_model=ProductRead)
async def update_product(
    product_id: UUID,
    data: ProductUpdate,
    admin: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    service: Annotated[ProductService, Depends(get_product_service)],
) -> Product:
    return await service.update_product(product_id, data)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_product(
    product_id: UUID,
    admin: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    service: Annotated[ProductService, Depends(get_product_service)],
) -> Response:
    await service.deactivate_product(product_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
