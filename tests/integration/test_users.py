import os
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User, UserRole

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)


async def test_create_user_with_default_customer_role(db_session: AsyncSession) -> None:
    user = User(email="customer@example.test", password_hash="test-hash", full_name="Test User")
    db_session.add(user)
    await db_session.flush()
    user_id = user.id
    db_session.expunge_all()

    saved_user = await db_session.get(User, user_id)

    assert isinstance(user_id, UUID)
    assert saved_user is not None
    assert saved_user.email == "customer@example.test"
    assert saved_user.full_name == "Test User"
    assert saved_user.password_hash == "test-hash"
    assert saved_user.role is UserRole.CUSTOMER
    assert saved_user.is_active is True


@pytest.mark.parametrize("role", [UserRole.CUSTOMER, UserRole.MANAGER, UserRole.ADMIN])
async def test_allowed_roles_are_saved(db_session: AsyncSession, role: UserRole) -> None:
    user = User(
        email="role@example.test", password_hash="test-hash", full_name="Test User", role=role
    )
    db_session.add(user)
    await db_session.flush()
    user_id = user.id
    db_session.expunge_all()

    saved_user = await db_session.get(User, user_id)

    assert saved_user is not None
    assert saved_user.role is role


async def test_duplicate_email_is_rejected(db_session: AsyncSession) -> None:
    db_session.add(User(email="same@example.test", password_hash="hash", full_name="First"))
    await db_session.flush()
    db_session.add(User(email="same@example.test", password_hash="hash", full_name="Second"))

    with pytest.raises(IntegrityError) as error:
        await db_session.flush()

    assert "ix_users_email" in str(error.value.orig)


async def test_invalid_role_is_rejected_by_database(db_session: AsyncSession) -> None:
    user = User(email="role@example.test", password_hash="hash", full_name="Test User")
    db_session.add(user)
    await db_session.flush()

    with pytest.raises(IntegrityError) as error:
        await db_session.execute(
            text("UPDATE users SET role = 'owner' WHERE id = :user_id"), {"user_id": user.id}
        )

    assert "ck_users_user_role" in str(error.value.orig)


async def test_default_timestamps_are_timezone_aware_utc(db_session: AsyncSession) -> None:
    user = User(email="timestamps@example.test", password_hash="hash", full_name="Test User")
    db_session.add(user)
    await db_session.flush()
    user_id = user.id
    db_session.expunge_all()

    saved_user = await db_session.get(User, user_id)
    assert saved_user is not None
    assert saved_user.created_at.utcoffset() == timedelta(0)
    assert saved_user.updated_at.utcoffset() == timedelta(0)
    assert await db_session.scalar(text("SHOW TIME ZONE")) == "UTC"

    result = await db_session.execute(
        text(
            "SELECT pg_typeof(created_at)::text, pg_typeof(updated_at)::text "
            "FROM users WHERE id = :user_id"
        ),
        {"user_id": user_id},
    )
    assert tuple(result.one()) == ("timestamp with time zone", "timestamp with time zone")


async def test_timestamp_offsets_preserve_the_same_utc_instants(db_session: AsyncSession) -> None:
    created_at = datetime(2025, 1, 10, 15, 30, tzinfo=timezone(timedelta(hours=5)))
    updated_at = datetime(2025, 6, 15, 8, 45, tzinfo=timezone(timedelta(hours=-4)))
    user = User(
        email="offsets@example.test",
        password_hash="hash",
        full_name="Test User",
        created_at=created_at,
        updated_at=updated_at,
    )
    db_session.add(user)
    await db_session.flush()
    user_id = user.id
    db_session.expunge_all()

    saved_user = await db_session.get(User, user_id)

    assert saved_user is not None
    assert saved_user.created_at == created_at.astimezone(UTC)
    assert saved_user.updated_at == updated_at.astimezone(UTC)
    assert saved_user.created_at.utcoffset() == timedelta(0)
    assert saved_user.updated_at.utcoffset() == timedelta(0)
