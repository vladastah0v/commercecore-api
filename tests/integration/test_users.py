import os
from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.database import create_database_engine
from app.modules.users.models import User, UserRole

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)


@pytest_asyncio.fixture
async def user_session(
    migration_database: str,
    run_alembic: Callable[[str, str, str], Awaitable[None]],
    monkeypatch,
) -> AsyncIterator[AsyncSession]:
    await run_alembic(migration_database, "upgrade", "head")
    monkeypatch.setenv("POSTGRES_USER", "commercecore_test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-only-password")
    monkeypatch.setenv("POSTGRES_DB", migration_database)
    monkeypatch.setenv("COMMERCECORE_POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("COMMERCECORE_POSTGRES_PORT", "55432")
    monkeypatch.setenv("COMMERCECORE_DEBUG", "false")
    monkeypatch.setenv("COMMERCECORE_REDIS_HOST", "127.0.0.1")
    monkeypatch.setenv("COMMERCECORE_REDIS_PORT", "56379")
    engine = create_database_engine(Settings(_env_file=None))
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()


async def test_create_user_with_default_customer_role(user_session: AsyncSession) -> None:
    user = User(email="customer@example.test", password_hash="test-hash", full_name="Test User")
    user_session.add(user)
    await user_session.flush()
    user_id = user.id
    user_session.expunge_all()

    saved_user = await user_session.get(User, user_id)

    assert isinstance(user_id, UUID)
    assert saved_user is not None
    assert saved_user.email == "customer@example.test"
    assert saved_user.full_name == "Test User"
    assert saved_user.password_hash == "test-hash"
    assert saved_user.role is UserRole.CUSTOMER
    assert saved_user.is_active is True


@pytest.mark.parametrize("role", [UserRole.CUSTOMER, UserRole.MANAGER, UserRole.ADMIN])
async def test_allowed_roles_are_saved(user_session: AsyncSession, role: UserRole) -> None:
    user = User(
        email="role@example.test", password_hash="test-hash", full_name="Test User", role=role
    )
    user_session.add(user)
    await user_session.flush()
    user_id = user.id
    user_session.expunge_all()

    saved_user = await user_session.get(User, user_id)

    assert saved_user is not None
    assert saved_user.role is role


async def test_duplicate_email_is_rejected(user_session: AsyncSession) -> None:
    user_session.add(User(email="same@example.test", password_hash="hash", full_name="First"))
    await user_session.flush()
    user_session.add(User(email="same@example.test", password_hash="hash", full_name="Second"))

    with pytest.raises(IntegrityError) as error:
        await user_session.flush()

    assert "ix_users_email" in str(error.value.orig)


async def test_invalid_role_is_rejected_by_database(user_session: AsyncSession) -> None:
    user = User(email="role@example.test", password_hash="hash", full_name="Test User")
    user_session.add(user)
    await user_session.flush()

    with pytest.raises(IntegrityError) as error:
        await user_session.execute(
            text("UPDATE users SET role = 'owner' WHERE id = :user_id"), {"user_id": user.id}
        )

    assert "ck_users_user_role" in str(error.value.orig)
