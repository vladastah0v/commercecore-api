import os
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import Category

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)


async def test_create_category(db_session: AsyncSession) -> None:
    category = Category(name="Books", slug="books")
    db_session.add(category)
    await db_session.flush()
    category_id = category.id
    db_session.expunge_all()

    saved_category = await db_session.get(Category, category_id)

    assert isinstance(category_id, UUID)
    assert saved_category is not None
    assert saved_category.name == "Books"
    assert saved_category.slug == "books"
    assert saved_category.created_at.utcoffset() == timedelta(0)


async def test_duplicate_slug_is_rejected(db_session: AsyncSession) -> None:
    db_session.add(Category(name="Books", slug="books"))
    await db_session.flush()
    db_session.add(Category(name="Other books", slug="books"))

    with pytest.raises(IntegrityError) as error:
        await db_session.flush()

    assert "ix_categories_slug" in str(error.value.orig)


@pytest.mark.parametrize("missing_field", ["name", "slug"])
async def test_name_and_slug_are_required(db_session: AsyncSession, missing_field: str) -> None:
    values = {"id": uuid4(), "name": "Books", "slug": "books"}
    values[missing_field] = None

    with pytest.raises(IntegrityError) as error:
        await db_session.execute(
            text("INSERT INTO categories (id, name, slug) VALUES (:id, :name, :slug)"), values
        )

    assert f'null value in column "{missing_field}"' in str(error.value.orig)


async def test_created_at_preserves_utc_instant(db_session: AsyncSession) -> None:
    created_at = datetime(2025, 1, 10, 15, 30, tzinfo=timezone(timedelta(hours=5)))
    category = Category(name="Books", slug="books", created_at=created_at)
    db_session.add(category)
    await db_session.flush()
    category_id = category.id
    db_session.expunge_all()

    saved_category = await db_session.get(Category, category_id)

    assert saved_category is not None
    assert saved_category.created_at == created_at.astimezone(UTC)
    assert saved_category.created_at.utcoffset() == timedelta(0)
    column_type = await db_session.scalar(
        text("SELECT pg_typeof(created_at)::text FROM categories WHERE id = :category_id"),
        {"category_id": category_id},
    )
    assert column_type == "timestamp with time zone"
