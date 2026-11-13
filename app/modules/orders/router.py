from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.dependencies import get_current_user
from app.modules.orders.schemas import CheckoutRequest, OrderRead
from app.modules.orders.service import CheckoutService
from app.modules.users.models import User

router = APIRouter(prefix="/orders", tags=["orders"])


def get_checkout_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CheckoutService:
    return CheckoutService(session)


@router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def checkout(
    response: Response,
    data: CheckoutRequest,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[CheckoutService, Depends(get_checkout_service)],
    key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=255, pattern=r".*\S.*")
    ],
) -> OrderRead:
    result, created = await service.checkout(user.id, key, data)
    if not created:
        response.status_code = status.HTTP_200_OK
    return result
