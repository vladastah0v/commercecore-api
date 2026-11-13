import asyncio
import os

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import verify_password
from app.modules.auth.exceptions import EmailAlreadyRegisteredError
from app.modules.auth.schemas import RegisterRequest
from app.modules.auth.service import RegistrationService
from app.modules.users.admin_service import AdminBootstrapService
from app.modules.users.models import User, UserRole

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)


def admin_data(email: str = "ADMIN@example.com") -> RegisterRequest:
    return RegisterRequest(email=email, password="secure-password", full_name=" Admin User ")


async def test_admin_is_created_with_hashed_password(db_session: AsyncSession) -> None:
    admin = await AdminBootstrapService(db_session).create_admin(admin_data())
    admin_id = admin.id
    db_session.expunge_all()
    saved = await db_session.get(User, admin_id)
    assert saved is not None
    assert saved.email == "admin@example.com"
    assert saved.full_name == "Admin User"
    assert saved.role is UserRole.ADMIN and saved.is_active is True
    assert saved.password_hash.startswith("$argon2id$")
    assert await verify_password("secure-password", saved.password_hash)


async def test_existing_customer_is_not_promoted(db_session: AsyncSession) -> None:
    customer = await RegistrationService(db_session).register(admin_data())
    customer_id = customer.id
    with pytest.raises(EmailAlreadyRegisteredError):
        await AdminBootstrapService(db_session).create_admin(admin_data("admin@EXAMPLE.COM"))
    saved = await db_session.get(User, customer_id)
    assert saved is not None and saved.role is UserRole.CUSTOMER
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1


async def test_concurrent_creation_with_same_email_creates_one_admin(
    db_session: AsyncSession,
) -> None:
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def create() -> User:
        async with session_factory() as session:
            return await AdminBootstrapService(session).create_admin(admin_data())

    results = await asyncio.gather(create(), create(), return_exceptions=True)
    assert sum(isinstance(result, User) for result in results) == 1
    assert sum(isinstance(result, EmailAlreadyRegisteredError) for result in results) == 1
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1
