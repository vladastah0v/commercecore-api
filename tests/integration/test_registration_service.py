import asyncio
import os

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import verify_password
from app.modules.auth.exceptions import EmailAlreadyRegisteredError
from app.modules.auth.schemas import RegisterRequest
from app.modules.auth.service import RegistrationService
from app.modules.users.models import User, UserRole
from app.modules.users.repository import UserRepository

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)


def registration(email: str = "USER@example.com") -> RegisterRequest:
    return RegisterRequest(email=email, password="valid-password", full_name=" Test User ")


async def test_register_saves_customer_with_hashed_password(db_session: AsyncSession) -> None:
    user = await RegistrationService(db_session).register(registration())
    user_id = user.id
    db_session.expunge_all()

    saved = await db_session.get(User, user_id)

    assert saved is not None
    assert saved.email == "user@example.com"
    assert saved.full_name == "Test User"
    assert saved.role is UserRole.CUSTOMER
    assert saved.is_active is True
    assert saved.password_hash != "valid-password"
    assert saved.password_hash.startswith("$argon2id$")
    assert await verify_password("valid-password", saved.password_hash)


async def test_duplicate_email_is_rejected_and_session_can_be_reused(
    db_session: AsyncSession,
) -> None:
    service = RegistrationService(db_session)
    await service.register(registration())

    with pytest.raises(EmailAlreadyRegisteredError):
        await service.register(registration("user@EXAMPLE.COM"))

    other = await service.register(registration("other@example.com"))
    assert other.email == "other@example.com"
    count = await db_session.scalar(select(func.count()).select_from(User))
    assert count == 2


async def test_concurrent_registration_creates_only_one_user(db_session: AsyncSession) -> None:
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def register_once() -> User:
        async with session_factory() as session:
            return await RegistrationService(session).register(registration())

    results = await asyncio.gather(register_once(), register_once(), return_exceptions=True)

    assert sum(isinstance(result, User) for result in results) == 1
    assert sum(isinstance(result, EmailAlreadyRegisteredError) for result in results) == 1
    count = await db_session.scalar(select(func.count()).select_from(User))
    assert count == 1


async def test_unrelated_database_error_is_not_treated_as_duplicate_email(
    db_session: AsyncSession, monkeypatch
) -> None:
    add_user = UserRepository.add

    async def add_invalid_user(repository: UserRepository, user: User) -> None:
        user.full_name = None
        await add_user(repository, user)

    monkeypatch.setattr(UserRepository, "add", add_invalid_user)

    with pytest.raises(IntegrityError):
        await RegistrationService(db_session).register(registration())

    count = await db_session.scalar(select(func.count()).select_from(User))
    assert count == 0
