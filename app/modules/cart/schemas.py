from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Quantity = Annotated[int, Field(strict=True, gt=0, le=2147483647)]


class AddCartItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    quantity: Quantity


class UpdateCartItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: Quantity


class CartItemRead(BaseModel):
    product_id: UUID
    name: str
    price: Decimal
    is_active: bool
    quantity: int


class CartRead(BaseModel):
    id: UUID
    items: list[CartItemRead]
