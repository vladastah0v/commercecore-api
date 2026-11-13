from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import Product
from app.modules.catalog.schemas import ProductFilters


class ProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active(self, filters: ProductFilters) -> list[Product]:
        statement = select(Product).where(Product.is_active.is_(True))
        if filters.category_id is not None:
            statement = statement.where(Product.category_id == filters.category_id)
        if filters.search is not None:
            term = filters.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            statement = statement.where(Product.name.ilike(f"%{term}%", escape="\\"))
        if filters.min_price is not None:
            statement = statement.where(Product.price >= filters.min_price)
        if filters.max_price is not None:
            statement = statement.where(Product.price <= filters.max_price)
        if filters.sort == "price_asc":
            statement = statement.order_by(Product.price.asc(), Product.id)
        elif filters.sort == "price_desc":
            statement = statement.order_by(Product.price.desc(), Product.id)
        else:
            statement = statement.order_by(Product.name, Product.id)
        statement = statement.limit(filters.limit).offset(filters.offset)
        return list((await self._session.scalars(statement)).all())

    async def get_by_id(self, product_id: UUID, *, active_only: bool) -> Product | None:
        statement = select(Product).where(Product.id == product_id)
        if active_only:
            statement = statement.where(Product.is_active.is_(True))
        return await self._session.scalar(statement)

    async def save(self, product: Product) -> None:
        self._session.add(product)
        await self._session.flush()
