from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.exceptions import CategoryNotFoundError, CategorySlugConflictError
from app.modules.catalog.models import Category
from app.modules.catalog.repository import CategoryRepository
from app.modules.catalog.schemas import CategoryCreate, CategoryUpdate


class CategoryService:
    """Read categories; write operations commit or roll back the provided session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._categories = CategoryRepository(session)

    async def list_categories(self) -> list[Category]:
        return await self._categories.list_all()

    async def get_category(self, category_id: UUID) -> Category:
        category = await self._categories.get_by_id(category_id)
        if category is None:
            raise CategoryNotFoundError
        return category

    async def create_category(self, data: CategoryCreate) -> Category:
        category = Category(name=data.name, slug=data.slug)
        await self._save(category)
        return category

    async def update_category(self, category_id: UUID, data: CategoryUpdate) -> Category:
        try:
            category = await self.get_category(category_id)
            for field, value in data.model_dump(exclude_unset=True).items():
                setattr(category, field, value)
            await self._save(category)
        except CategoryNotFoundError:
            await self._session.rollback()
            raise
        return category

    async def _save(self, category: Category) -> None:
        try:
            await self._categories.save(category)
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            db_error = error.orig
            if (
                getattr(db_error, "sqlstate", None) == "23505"
                and getattr(db_error.__cause__, "constraint_name", None) == "ix_categories_slug"
            ):
                raise CategorySlugConflictError from None
            raise
        except Exception:
            await self._session.rollback()
            raise
