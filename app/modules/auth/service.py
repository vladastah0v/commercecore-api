from hashlib import sha256

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import hash_password, verify_password
from app.core.tokens import create_access_token, create_refresh_token, decode_token
from app.modules.auth.exceptions import EmailAlreadyRegisteredError, InvalidCredentialsError
from app.modules.auth.models import RefreshToken
from app.modules.auth.repository import RefreshTokenRepository
from app.modules.auth.schemas import LoginRequest, RegisterRequest, TokenPair
from app.modules.users.models import User, UserRole
from app.modules.users.repository import UserRepository


class RegistrationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)

    async def register(self, data: RegisterRequest) -> User:
        password_hash = await hash_password(data.password.get_secret_value())
        user = User(
            email=data.email,
            password_hash=password_hash,
            full_name=data.full_name,
            role=UserRole.CUSTOMER,
        )

        try:
            async with self._session.begin():
                await self._users.add(user)
        except IntegrityError as error:
            db_error = error.orig
            cause = db_error.__cause__
            if (
                getattr(db_error, "sqlstate", None) == "23505"
                and getattr(cause, "constraint_name", None) == "ix_users_email"
            ):
                raise EmailAlreadyRegisteredError from None
            raise

        return user


# Used only to keep password verification comparable for nonexistent accounts.
_DUMMY_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$QH5we70AHko6YSgvc5R2gA$"
    "1pW4g2DDH4iGw9r7bORrgWrLIRGDbGG+BMKkIXuEPt8"
)


class LoginService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._users = UserRepository(session)
        self._tokens = RefreshTokenRepository(session)

    async def login(self, data: LoginRequest) -> TokenPair:
        async with self._session.begin():
            user = await self._users.get_by_email(data.email)
            valid_password = await verify_password(
                data.password.get_secret_value(), user.password_hash if user else _DUMMY_HASH
            )
            if user is None or not user.is_active or not valid_password:
                raise InvalidCredentialsError

            access_token = create_access_token(user.id, self._settings)
            refresh_token = create_refresh_token(user.id, self._settings)
            claims = decode_token(refresh_token, "refresh", self._settings)
            await self._tokens.add(
                RefreshToken(
                    user_id=user.id,
                    token_hash=sha256(refresh_token.encode("utf-8")).hexdigest(),
                    expires_at=claims.expires_at,
                )
            )
        return TokenPair(access_token=access_token, refresh_token=refresh_token)
