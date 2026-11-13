import os
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import RefreshToken
from app.modules.users.models import User

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)

EXPIRATION = datetime(2030, 1, 1, tzinfo=UTC)


async def create_user(session: AsyncSession, email: str = "user@example.test") -> User:
    user = User(email=email, password_hash="test-hash", full_name="Test User")
    session.add(user)
    await session.flush()
    return user


async def test_create_refresh_token_for_existing_user(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    token = RefreshToken(user_id=user.id, token_hash="a" * 64, expires_at=EXPIRATION)
    db_session.add(token)
    await db_session.flush()
    token_id, user_id = token.id, user.id
    db_session.expunge_all()

    saved_token = await db_session.get(RefreshToken, token_id)

    assert isinstance(token_id, UUID)
    assert saved_token is not None
    assert saved_token.user_id == user_id
    assert saved_token.token_hash == "a" * 64
    assert saved_token.expires_at == EXPIRATION
    assert saved_token.revoked_at is None
    assert saved_token.created_at.utcoffset() == timedelta(0)


async def test_duplicate_hash_is_rejected_across_users(db_session: AsyncSession) -> None:
    first_user = await create_user(db_session, "first@example.test")
    second_user = await create_user(db_session, "second@example.test")
    db_session.add(RefreshToken(user_id=first_user.id, token_hash="a" * 64, expires_at=EXPIRATION))
    await db_session.flush()
    db_session.add(RefreshToken(user_id=second_user.id, token_hash="a" * 64, expires_at=EXPIRATION))

    with pytest.raises(IntegrityError) as error:
        await db_session.flush()

    assert "ix_refresh_tokens_token_hash" in str(error.value.orig)


async def test_token_for_nonexistent_user_is_rejected(db_session: AsyncSession) -> None:
    db_session.add(RefreshToken(user_id=uuid4(), token_hash="b" * 64, expires_at=EXPIRATION))

    with pytest.raises(IntegrityError) as error:
        await db_session.flush()

    assert "fk_refresh_tokens_user_id_users" in str(error.value.orig)


async def test_user_deletion_removes_refresh_tokens(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    token = RefreshToken(user_id=user.id, token_hash="c" * 64, expires_at=EXPIRATION)
    db_session.add(token)
    await db_session.flush()
    token_id = token.id

    await db_session.delete(user)
    await db_session.flush()
    db_session.expunge_all()

    assert await db_session.get(RefreshToken, token_id) is None


async def test_token_timestamps_preserve_utc_instants(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    expires_at = datetime(2030, 1, 10, 15, 30, tzinfo=timezone(timedelta(hours=5)))
    revoked_at = datetime(2029, 12, 15, 8, 45, tzinfo=timezone(timedelta(hours=-4)))
    token = RefreshToken(
        user_id=user.id,
        token_hash="d" * 64,
        expires_at=expires_at,
        revoked_at=revoked_at,
    )
    db_session.add(token)
    await db_session.flush()
    token_id = token.id
    db_session.expunge_all()

    saved_token = await db_session.get(RefreshToken, token_id)
    assert saved_token is not None
    assert saved_token.expires_at == expires_at.astimezone(UTC)
    assert saved_token.revoked_at == revoked_at.astimezone(UTC)
    assert saved_token.expires_at.utcoffset() == timedelta(0)
    assert saved_token.revoked_at.utcoffset() == timedelta(0)

    result = await db_session.execute(
        text(
            "SELECT pg_typeof(expires_at)::text, pg_typeof(revoked_at)::text "
            "FROM refresh_tokens WHERE id = :token_id"
        ),
        {"token_id": token_id},
    )
    assert tuple(result.one()) == ("timestamp with time zone", "timestamp with time zone")
