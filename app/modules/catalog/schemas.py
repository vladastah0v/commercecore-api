from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema

CategoryName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
CategorySlug = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=255,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: CategoryName
    slug: CategorySlug


class CategoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: CategoryName | SkipJsonSchema[None] = None
    slug: CategorySlug | SkipJsonSchema[None] = None

    @model_validator(mode="before")
    @classmethod
    def require_changes(cls, value: Any) -> Any:
        if isinstance(value, dict) and not value:
            raise ValueError("At least one field must be provided")
        return value

    @field_validator("name", "slug", mode="before")
    @classmethod
    def reject_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Field cannot be null")
        return value


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    created_at: datetime


Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2, allow_inf_nan=False)]
StockQuantity = Annotated[int, Field(strict=True, ge=0, le=2147483647)]


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: UUID
    name: CategoryName
    slug: CategorySlug
    description: str | None = None
    price: Money
    stock_quantity: StockQuantity = 0
    is_active: bool = Field(default=True, strict=True)

    @field_validator("price", mode="before")
    @classmethod
    def reject_float_price(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("Price must be a decimal string or integer")
        return value


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: UUID | SkipJsonSchema[None] = None
    name: CategoryName | SkipJsonSchema[None] = None
    slug: CategorySlug | SkipJsonSchema[None] = None
    description: str | None = None
    price: Money | SkipJsonSchema[None] = None
    stock_quantity: StockQuantity | SkipJsonSchema[None] = None
    is_active: Annotated[bool, Field(strict=True)] | SkipJsonSchema[None] = None

    @model_validator(mode="before")
    @classmethod
    def require_changes(cls, value: Any) -> Any:
        if isinstance(value, dict) and not value:
            raise ValueError("At least one field must be provided")
        return value

    @field_validator(
        "category_id", "name", "slug", "price", "stock_quantity", "is_active", mode="before"
    )
    @classmethod
    def reject_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Field cannot be null")
        return value

    @field_validator("price", mode="before")
    @classmethod
    def reject_float_price(cls, value: Any) -> Any:
        return ProductCreate.reject_float_price(value)


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category_id: UUID
    name: str
    slug: str
    description: str | None
    price: Decimal
    stock_quantity: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=2147483647)
    category_id: UUID | None = None
    search: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
        | None
    ) = None
    min_price: Money | None = None
    max_price: Money | None = None
    sort: Literal["price_asc", "price_desc"] | None = None

    @model_validator(mode="after")
    def validate_price_range(self) -> "ProductFilters":
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("min_price must not exceed max_price")
        return self
