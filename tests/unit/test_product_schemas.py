from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.catalog.schemas import ProductCreate, ProductFilters, ProductUpdate


def product(**changes) -> dict:
    return {"category_id": uuid4(), "name": "Book", "slug": "book", "price": "12.30", **changes}


def test_product_price_uses_decimal_and_defaults() -> None:
    result = ProductCreate.model_validate(product())
    assert result.price == Decimal("12.30")
    assert isinstance(result.price, Decimal)
    assert result.stock_quantity == 0
    assert result.is_active is True


@pytest.mark.parametrize("price", [-1, "1.234", "10000000000.00", "NaN", 1.25])
def test_invalid_price_is_rejected(price) -> None:
    with pytest.raises(ValidationError):
        ProductCreate.model_validate(product(price=price))


@pytest.mark.parametrize("quantity", [-1, 1.5, True, 2147483648])
def test_invalid_stock_is_rejected(quantity) -> None:
    with pytest.raises(ValidationError):
        ProductCreate.model_validate(product(stock_quantity=quantity))


def test_update_supports_explicit_description_removal() -> None:
    result = ProductUpdate.model_validate({"description": None, "price": "0.00"})
    assert result.model_dump(exclude_unset=True) == {"description": None, "price": Decimal("0.00")}


@pytest.mark.parametrize(
    "payload", [{}, {"name": None}, {"price": None}, {"price": 1.5}, {"other": "value"}]
)
def test_invalid_product_update_is_rejected(payload: dict) -> None:
    with pytest.raises(ValidationError):
        ProductUpdate.model_validate(payload)


def test_invalid_price_range_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ProductFilters(min_price=Decimal("20"), max_price=Decimal("10"))
