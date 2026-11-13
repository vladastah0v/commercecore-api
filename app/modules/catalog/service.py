from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.exceptions import CategoryNotFoundError
from app.modules.catalog.models import Category
from app.modules.catalog.repository import CategoryRepository


class CategoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._categories = CategoryRepository(session)

    async def list_categories(self) -> list[Category]:
        return await self._categories.list_all()

    async def get_category(self, category_id: UUID) -> Category:
        category = await self._categories.get_by_id(category_id)
        if category is None:
            raise CategoryNotFoundError
        return category
