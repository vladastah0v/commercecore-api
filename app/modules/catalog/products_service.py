from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.exceptions import (
    CategoryNotFoundError,
    ProductNotFoundError,
    ProductSlugConflictError,
)
from app.modules.catalog.models import Category, Product
from app.modules.catalog.products_repository import ProductRepository
from app.modules.catalog.schemas import ProductCreate, ProductFilters, ProductUpdate


class ProductService:
    """Read products; write operations commit or roll back the provided session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._products = ProductRepository(session)

    async def list_products(self, filters: ProductFilters) -> list[Product]:
        return await self._products.list_active(filters)

    async def get_product(self, product_id: UUID, *, active_only: bool = True) -> Product:
        product = await self._products.get_by_id(product_id, active_only=active_only)
        if product is None:
            raise ProductNotFoundError
        return product

    async def _require_category(self, category_id: UUID) -> None:
        if await self._session.get(Category, category_id) is None:
            raise CategoryNotFoundError

    async def create_product(self, data: ProductCreate) -> Product:
        try:
            await self._require_category(data.category_id)
            product = Product(**data.model_dump())
            await self._save(product)
            return product
        except CategoryNotFoundError:
            await self._session.rollback()
            raise

    async def update_product(self, product_id: UUID, data: ProductUpdate) -> Product:
        try:
            product = await self.get_product(product_id, active_only=False)
            changes = data.model_dump(exclude_unset=True)
            if "category_id" in changes:
                await self._require_category(changes["category_id"])
            for field, value in changes.items():
                setattr(product, field, value)
            await self._save(product)
            return product
        except (CategoryNotFoundError, ProductNotFoundError):
            await self._session.rollback()
            raise

    async def deactivate_product(self, product_id: UUID) -> None:
        try:
            product = await self.get_product(product_id, active_only=False)
            product.is_active = False
            await self._save(product)
        except ProductNotFoundError:
            await self._session.rollback()
            raise

    async def _save(self, product: Product) -> None:
        try:
            await self._products.save(product)
            await self._session.refresh(product)
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            db_error = error.orig
            constraint = getattr(db_error.__cause__, "constraint_name", None)
            if getattr(db_error, "sqlstate", None) == "23505" and constraint == "ix_products_slug":
                raise ProductSlugConflictError from None
            if (
                getattr(db_error, "sqlstate", None) == "23503"
                and constraint == "fk_products_category_id_categories"
            ):
                raise CategoryNotFoundError from None
            raise
        except Exception:
            await self._session.rollback()
            raise
