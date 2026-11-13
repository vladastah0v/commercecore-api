from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.catalog.models import Category
from app.modules.catalog.schemas import CategoryCreate, CategoryRead, CategoryUpdate


def test_create_trims_fields() -> None:
    category = CategoryCreate(name=" Книги ", slug=" books-and-magazines ")
    assert category.name == "Книги"
    assert category.slug == "books-and-magazines"


@pytest.mark.parametrize("name", ["", "   ", "x" * 256])
def test_invalid_name_is_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        CategoryCreate(name=name, slug="books")


@pytest.mark.parametrize(
    "slug", ["", "Bad-Slug", "two words", "bad_slug", "-books", "books-", "a--b", "x" * 256]
)
def test_invalid_slug_is_rejected(slug: str) -> None:
    with pytest.raises(ValidationError):
        CategoryCreate(name="Books", slug=slug)


def test_update_only_includes_supplied_fields() -> None:
    assert CategoryUpdate(name=" New name ").model_dump(exclude_unset=True) == {"name": "New name"}
    assert CategoryUpdate(slug="new-slug").model_dump(exclude_unset=True) == {"slug": "new-slug"}


@pytest.mark.parametrize("payload", [{}, {"name": None}, {"slug": None}, {"other": "value"}])
def test_invalid_update_is_rejected(payload: dict) -> None:
    with pytest.raises(ValidationError):
        CategoryUpdate.model_validate(payload)


def test_read_from_orm_model() -> None:
    category_id = uuid4()
    created_at = datetime(2025, 1, 1, tzinfo=UTC)
    model = Category(id=category_id, name="Books", slug="books", created_at=created_at)
    result = CategoryRead.model_validate(model)
    assert result.id == category_id
    assert result.name == "Books"
    assert result.slug == "books"
    assert result.created_at == created_at
