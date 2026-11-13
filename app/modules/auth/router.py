from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.schemas import RegisterRequest
from app.modules.auth.service import RegistrationService
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


def get_registration_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RegistrationService:
    return RegistrationService(session)


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"description": "Email is already registered"}},
)
async def register(
    data: RegisterRequest,
    service: Annotated[RegistrationService, Depends(get_registration_service)],
) -> UserRead:
    user = await service.register(data)
    return UserRead.model_validate(user)
