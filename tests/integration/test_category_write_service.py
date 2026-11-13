import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.catalog.exceptions import CategoryNotFoundError, CategorySlugConflictError
from app.modules.catalog.models import Category
from app.modules.catalog.repository import CategoryRepository
from app.modules.catalog.schemas import CategoryCreate, CategoryUpdate
from app.modules.catalog.service import CategoryService

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)


async def test_create_persists_category_with_existing_transaction(db_session: AsyncSession) -> None:
    await db_session.scalar(select(func.count()).select_from(Category))
    category = await CategoryService(db_session).create_category(
        CategoryCreate(name=" Books ", slug="books")
    )
    category_id = category.id
    db_session.expunge_all()

    saved = await db_session.get(Category, category_id)
    assert saved is not None
    assert saved.name == "Books"
    assert saved.slug == "books"


async def test_update_changes_only_supplied_fields(db_session: AsyncSession) -> None:
    service = CategoryService(db_session)
    created = await service.create_category(CategoryCreate(name="Books", slug="books"))
    category_id = created.id
    updated = await service.update_category(category_id, CategoryUpdate(name="New name"))
    assert updated.name == "New name"
    assert updated.slug == "books"
    updated = await service.update_category(category_id, CategoryUpdate(slug="new-slug"))
    assert updated.name == "New name"
    assert updated.slug == "new-slug"


async def test_updating_missing_category_raises_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(CategoryNotFoundError):
        await CategoryService(db_session).update_category(uuid4(), CategoryUpdate(name="New"))


async def test_duplicate_slug_rolls_back_and_preserves_existing_data(
    db_session: AsyncSession,
) -> None:
    service = CategoryService(db_session)
    await service.create_category(CategoryCreate(name="Books", slug="books"))
    other = await service.create_category(CategoryCreate(name="Music", slug="music"))
    other_id = other.id

    with pytest.raises(CategorySlugConflictError):
        await service.create_category(CategoryCreate(name="Duplicate", slug="books"))
    with pytest.raises(CategorySlugConflictError):
        await service.update_category(other_id, CategoryUpdate(name="Changed", slug="books"))

    saved = await service.get_category(other_id)
    assert saved.name == "Music"
    assert saved.slug == "music"
    assert await db_session.scalar(select(func.count()).select_from(Category)) == 2


async def test_concurrent_creation_allows_only_one_matching_slug(db_session: AsyncSession) -> None:
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def create() -> Category:
        async with session_factory() as session:
            return await CategoryService(session).create_category(
                CategoryCreate(name="Books", slug="books")
            )

    results = await asyncio.gather(create(), create(), return_exceptions=True)
    assert sum(isinstance(result, Category) for result in results) == 1
    assert sum(isinstance(result, CategorySlugConflictError) for result in results) == 1
    assert await db_session.scalar(select(func.count()).select_from(Category)) == 1


async def test_other_integrity_errors_are_not_reported_as_slug_conflicts(
    db_session: AsyncSession, monkeypatch
) -> None:
    save = CategoryRepository.save

    async def save_invalid(repository: CategoryRepository, category: Category) -> None:
        category.name = None
        await save(repository, category)

    monkeypatch.setattr(CategoryRepository, "save", save_invalid)
    with pytest.raises(IntegrityError):
        await CategoryService(db_session).create_category(
            CategoryCreate(name="Books", slug="books")
        )
    assert await db_session.scalar(select(func.count()).select_from(Category)) == 0
