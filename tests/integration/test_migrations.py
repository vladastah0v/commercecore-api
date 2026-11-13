import os
from collections.abc import Awaitable, Callable
from uuid import uuid4

import asyncpg
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)

INITIAL_REVISION = "95bce674efaa"
REFRESH_TOKENS_REVISION = "db5aa9e611a7"


async def test_initial_migration_can_be_applied_rolled_back_and_reapplied(
    migration_database: str,
    test_database_connection: asyncpg.Connection,
    run_alembic: Callable[[str, str, str], Awaitable[None]],
) -> None:
    connection = test_database_connection

    await run_alembic(migration_database, "upgrade", INITIAL_REVISION)
    assert await connection.fetchval("SELECT to_regclass('public.users')") is not None
    version = await connection.fetchval("SELECT version_num FROM alembic_version")
    assert version == INITIAL_REVISION

    await run_alembic(migration_database, "downgrade", "base")
    assert await connection.fetchval("SELECT to_regclass('public.users')") is None
    assert await connection.fetchval("SELECT count(*) FROM alembic_version") == 0

    await run_alembic(migration_database, "upgrade", INITIAL_REVISION)
    assert await connection.fetchval("SELECT to_regclass('public.users')") is not None
    version = await connection.fetchval("SELECT version_num FROM alembic_version")
    assert version == INITIAL_REVISION


async def test_refresh_tokens_migration_can_be_applied_rolled_back_and_reapplied(
    migration_database: str,
    test_database_connection: asyncpg.Connection,
    run_alembic: Callable[[str, str, str], Awaitable[None]],
) -> None:
    connection = test_database_connection
    await run_alembic(migration_database, "upgrade", INITIAL_REVISION)
    user_id = uuid4()
    await connection.execute(
        "INSERT INTO users (id, email, password_hash, full_name) VALUES ($1, $2, $3, $4)",
        user_id,
        "user@example.test",
        "test-hash",
        "Test User",
    )

    await run_alembic(migration_database, "upgrade", REFRESH_TOKENS_REVISION)
    assert await connection.fetchval("SELECT to_regclass('public.refresh_tokens')") is not None
    assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
        REFRESH_TOKENS_REVISION
    )

    await run_alembic(migration_database, "downgrade", INITIAL_REVISION)
    assert await connection.fetchval("SELECT to_regclass('public.refresh_tokens')") is None
    assert await connection.fetchval("SELECT to_regclass('public.users')") is not None
    assert await connection.fetchval("SELECT email FROM users WHERE id = $1", user_id) == (
        "user@example.test"
    )
    assert await connection.fetchval("SELECT version_num FROM alembic_version") == INITIAL_REVISION

    await run_alembic(migration_database, "upgrade", REFRESH_TOKENS_REVISION)
    assert await connection.fetchval("SELECT to_regclass('public.refresh_tokens')") is not None
    assert await connection.fetchval("SELECT email FROM users WHERE id = $1", user_id) == (
        "user@example.test"
    )
    assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
        REFRESH_TOKENS_REVISION
    )
