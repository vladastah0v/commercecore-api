from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.modules.auth.exceptions import EmailAlreadyRegisteredError
from app.modules.auth.schemas import RegisterRequest
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
