from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.modules.auth.rate_limit import check_login_rate_limit
from app.modules.auth.schemas import LoginRequest, RefreshTokenRequest, RegisterRequest, TokenPair
from app.modules.auth.service import LoginService, RefreshService, RegistrationService
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
    "/login",
    response_model=TokenPair,
    dependencies=[Depends(check_login_rate_limit)],
    responses={
        401: {"description": "Invalid credentials"},
        429: {"description": "Too many login attempts"},
        503: {"description": "Login temporarily unavailable"},
    },
)
async def login(
    data: LoginRequest,
    response: Response,
    service: Annotated[LoginService, Depends(get_login_service)],
) -> TokenPair:
    response.headers["Cache-Control"] = "no-store"
    return await service.login(data)


def get_refresh_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RefreshService:
    return RefreshService(session, settings)


@router.post(
    "/refresh", response_model=TokenPair, responses={401: {"description": "Invalid token"}}
)
async def refresh(
    data: RefreshTokenRequest,
    response: Response,
    service: Annotated[RefreshService, Depends(get_refresh_service)],
) -> TokenPair:
    response.headers["Cache-Control"] = "no-store"
    return await service.refresh(data.refresh_token.get_secret_value())


@router.post("/logout", status_code=204, responses={401: {"description": "Invalid token"}})
async def logout(
    data: RefreshTokenRequest,
    service: Annotated[RefreshService, Depends(get_refresh_service)],
) -> Response:
    await service.logout(data.refresh_token.get_secret_value())
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
