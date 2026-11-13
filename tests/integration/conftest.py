import asyncio
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.database import create_database_engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
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


@pytest_asyncio.fixture
async def test_database_connection(migration_database: str) -> AsyncIterator[asyncpg.Connection]:
    connection = await asyncpg.connect(**TEST_CONNECTION, database=migration_database)
    try:
        yield connection
    finally:
        await connection.close()


@pytest.fixture
def run_alembic() -> Callable[[str, str, str], Awaitable[None]]:
    async def run(database_name: str, command: str, revision: str) -> None:
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

    return run


@pytest_asyncio.fixture
async def db_session(
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
