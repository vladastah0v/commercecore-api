import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.exceptions import CategoryNotFoundError
from app.modules.catalog.models import Category
from app.modules.catalog.service import CategoryService

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)


async def test_empty_list_and_missing_category(db_session: AsyncSession) -> None:
    service = CategoryService(db_session)
    assert await service.list_categories() == []
    with pytest.raises(CategoryNotFoundError):
        await service.get_category(uuid4())


async def test_categories_are_read_in_stable_order(db_session: AsyncSession) -> None:
    categories = [
        Category(name="Zulu", slug="zulu"),
        Category(name="Alpha", slug="alpha-one"),
        Category(name="Alpha", slug="alpha-two"),
    ]
    db_session.add_all(categories)
    await db_session.flush()
    expected_ids = sorted([categories[1].id, categories[2].id]) + [categories[0].id]
    db_session.expunge_all()

    result = await CategoryService(db_session).list_categories()

    assert [category.id for category in result] == expected_ids
    assert [category.name for category in result] == ["Alpha", "Alpha", "Zulu"]


async def test_category_can_be_read_by_id(db_session: AsyncSession) -> None:
    category = Category(name="Books", slug="books")
    db_session.add(category)
    await db_session.flush()
    category_id = category.id
    db_session.expunge_all()

    result = await CategoryService(db_session).get_category(category_id)

    assert result.id == category_id
    assert result.name == "Books"
    assert result.slug == "books"
