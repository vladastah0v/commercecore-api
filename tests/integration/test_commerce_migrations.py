import os
from collections.abc import Awaitable, Callable
from uuid import uuid4

import asyncpg
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)


@pytest.mark.parametrize(
    ("previous_revision", "revision", "tables"),
    [
        ("70558283546e", "3fef0819d344", ("products",)),
        ("3fef0819d344", "94b1b145a0dd", ("carts", "cart_items")),
        ("94b1b145a0dd", "54e8c678c16a", ("orders", "order_items")),
    ],
)
async def test_migration_upgrade_downgrade_and_reupgrade(
    migration_database: str,
    test_database_connection: asyncpg.Connection,
    run_alembic: Callable[[str, str, str], Awaitable[None]],
    previous_revision: str,
    revision: str,
    tables: tuple[str, ...],
) -> None:
    connection = test_database_connection
    await run_alembic(migration_database, "upgrade", previous_revision)
    category_id = uuid4()
    await connection.execute(
        "INSERT INTO categories (id, name, slug) VALUES ($1, $2, $3)",
        category_id,
        "Books",
        "books",
    )

    await run_alembic(migration_database, "upgrade", revision)
    for table in tables:
        assert await connection.fetchval("SELECT to_regclass($1)", f"public.{table}") is not None
    assert await connection.fetchval("SELECT version_num FROM alembic_version") == revision

    await run_alembic(migration_database, "downgrade", previous_revision)
    for table in tables:
        assert await connection.fetchval("SELECT to_regclass($1)", f"public.{table}") is None
    assert await connection.fetchval("SELECT name FROM categories WHERE id = $1", category_id) == (
        "Books"
    )
    assert await connection.fetchval("SELECT version_num FROM alembic_version") == previous_revision

    await run_alembic(migration_database, "upgrade", revision)
    for table in tables:
        assert await connection.fetchval("SELECT to_regclass($1)", f"public.{table}") is not None
    assert await connection.fetchval("SELECT name FROM categories WHERE id = $1", category_id) == (
        "Books"
    )
    assert await connection.fetchval("SELECT version_num FROM alembic_version") == revision
