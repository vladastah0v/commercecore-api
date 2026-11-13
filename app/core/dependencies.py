from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.core.tokens import InvalidTokenError, decode_token
from app.modules.auth.exceptions import AuthenticationRequiredError, InsufficientPermissionsError
from app.modules.users.models import User, UserRole
from app.modules.users.repository import UserRepository

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    if credentials is None:
        raise AuthenticationRequiredError
    try:
        claims = decode_token(credentials.credentials, "access", settings)
    except InvalidTokenError:
        raise AuthenticationRequiredError from None
    user = await UserRepository(session).get_by_id(claims.user_id)
    if user is None or not user.is_active:
        raise AuthenticationRequiredError
    return user


def require_roles(*roles: UserRole) -> Callable[..., Awaitable[User]]:
    async def check_role(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise InsufficientPermissionsError
        return user

    return check_role
