from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.modules.auth.exceptions import EmailAlreadyRegisteredError
from app.modules.auth.schemas import RegisterRequest
from app.modules.users.models import User, UserRole
from app.modules.users.repository import UserRepository, is_duplicate_email


class AdminBootstrapService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)

    async def create_admin(self, data: RegisterRequest) -> User:
        password_hash = await hash_password(data.password.get_secret_value())
        user = User(
            email=data.email,
            full_name=data.full_name,
            password_hash=password_hash,
            role=UserRole.ADMIN,
        )
        try:
            async with self._session.begin():
                await self._users.add(user)
        except IntegrityError as error:
            if is_duplicate_email(error):
                raise EmailAlreadyRegisteredError from None
            raise
        return user
