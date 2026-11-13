from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator
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
