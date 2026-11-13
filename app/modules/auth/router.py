from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.modules.auth.schemas import LoginRequest, RegisterRequest, TokenPair
from app.modules.auth.service import LoginService, RegistrationService
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


def get_login_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LoginService:
    return LoginService(session, settings)


@router.post(
    "/login", response_model=TokenPair, responses={401: {"description": "Invalid credentials"}}
)
async def login(
    data: LoginRequest,
    response: Response,
    service: Annotated[LoginService, Depends(get_login_service)],
) -> TokenPair:
    response.headers["Cache-Control"] = "no-store"
    return await service.login(data)
