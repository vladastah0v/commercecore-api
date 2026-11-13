from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.dependencies import require_roles
from app.modules.catalog.models import Category
from app.modules.catalog.schemas import CategoryCreate, CategoryRead, CategoryUpdate
from app.modules.catalog.service import CategoryService
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/categories", tags=["categories"])


def get_category_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CategoryService:
    return CategoryService(session)


@router.get("", response_model=list[CategoryRead])
async def list_categories(
    service: Annotated[CategoryService, Depends(get_category_service)],
) -> list[Category]:
    return await service.list_categories()


@router.get(
    "/{category_id}",
    response_model=CategoryRead,
    responses={404: {"description": "Category not found"}},
)
async def get_category(
    category_id: UUID,
    service: Annotated[CategoryService, Depends(get_category_service)],
) -> Category:
    return await service.get_category(category_id)


@router.post(
    "",
    response_model=CategoryRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        403: {"description": "Insufficient permissions"},
        409: {"description": "Slug already in use"},
    },
)
async def create_category(
    data: CategoryCreate,
    admin: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    service: Annotated[CategoryService, Depends(get_category_service)],
) -> Category:
    return await service.create_category(data)


@router.patch(
    "/{category_id}",
    response_model=CategoryRead,
    responses={
        403: {"description": "Insufficient permissions"},
        404: {"description": "Category not found"},
        409: {"description": "Slug already in use"},
    },
)
async def update_category(
    category_id: UUID,
    data: CategoryUpdate,
    admin: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    service: Annotated[CategoryService, Depends(get_category_service)],
) -> Category:
    return await service.update_category(category_id, data)
