import asyncio
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INITIAL_REVISION = "95bce674efaa"
TEST_CONNECTION = {
    "host": "127.0.0.1",
    "port": 55432,
    "user": "commercecore_test",
    "password": "test-only-password",
}


@pytest_asyncio.fixture
async def migration_database() -> AsyncIterator[str]:
    database_name = f"cc_migration_test_{uuid4().hex}"
    admin = await asyncpg.connect(**TEST_CONNECTION, database="commercecore_test")
    try:
        # The identifier contains only a fixed prefix and generated hexadecimal characters.
        await admin.execute(f'CREATE DATABASE "{database_name}"')
        try:
            yield database_name
        finally:
            await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
    finally:
        await admin.close()


async def run_alembic(database_name: str, command: str, revision: str) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "COMMERCECORE_POSTGRES_HOST": TEST_CONNECTION["host"],
            "COMMERCECORE_POSTGRES_PORT": str(TEST_CONNECTION["port"]),
            "POSTGRES_USER": TEST_CONNECTION["user"],
            "POSTGRES_PASSWORD": TEST_CONNECTION["password"],
            "POSTGRES_DB": database_name,
            "COMMERCECORE_DEBUG": "false",
            "COMMERCECORE_REDIS_HOST": "127.0.0.1",
            "COMMERCECORE_REDIS_PORT": "56379",
        }
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        command,
        revision,
        cwd=PROJECT_ROOT,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, (stdout + stderr).decode(errors="replace")


async def test_initial_migration_can_be_applied_rolled_back_and_reapplied(
    migration_database: str,
) -> None:
    connection = await asyncpg.connect(**TEST_CONNECTION, database=migration_database)
    try:
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
    finally:
        await connection.close()
