import os
from collections.abc import Awaitable, Callable

import asyncpg
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)

INITIAL_REVISION = "95bce674efaa"


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
