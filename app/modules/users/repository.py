from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User


def is_duplicate_email(error: IntegrityError) -> bool:
    db_error = error.orig
    return (
        getattr(db_error, "sqlstate", None) == "23505"
        and getattr(db_error.__cause__, "constraint_name", None) == "ix_users_email"
    )


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> None:
        self._session.add(user)
        await self._session.flush()

    async def get_by_email(self, email: str) -> User | None:
        return await self._session.scalar(select(User).where(User.email == email))

    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)
