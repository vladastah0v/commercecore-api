from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import Category


class CategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> list[Category]:
        statement = select(Category).order_by(Category.name, Category.id)
        return list((await self._session.scalars(statement)).all())

    async def get_by_id(self, category_id: UUID) -> Category | None:
        return await self._session.get(Category, category_id)

    async def save(self, category: Category) -> None:
        self._session.add(category)
        await self._session.flush()
