from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.orders.models import OrderStatus


class CheckoutItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    quantity: Annotated[int, Field(strict=True, gt=0, le=2147483647)]


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CheckoutItem] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_products_are_unique(self) -> "CheckoutRequest":
        if len({item.product_id for item in self.items}) != len(self.items):
            raise ValueError("Each product can appear only once")
        return self


class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    product_name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class OrderRead(BaseModel):
    id: UUID
    status: OrderStatus
    total_amount: Decimal
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemRead]
