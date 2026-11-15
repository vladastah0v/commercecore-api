import asyncio
import os
import sys
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.catalog.models import Category, Product
from scripts.seed import seed_catalog

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)


async def test_seed_cli_is_repeatable_and_preserves_existing_data(db_session: AsyncSession) -> None:
    category = Category(slug="home-office", name="Моя категория")
    db_session.add(category)
    await db_session.flush()
    db_session.add(
        Product(
            category_id=category.id,
            slug="demo-home-office-01",
            name="Мой товар",
            price=Decimal("42.00"),
            stock_quantity=2,
            is_active=False,
        )
    )
    await db_session.commit()

    async def run_cli() -> str:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "scripts.seed",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        assert process.returncode == 0, stderr.decode()
        return stdout.decode()

    assert "Created 4 categories and 99 products" in await run_cli()
    assert "Created 0 categories and 0 products" in await run_cli()
    assert await db_session.scalar(select(func.count()).select_from(Category)) == 5
    assert await db_session.scalar(select(func.count()).select_from(Product)) == 100
    db_session.expire_all()
    saved_category = await db_session.scalar(select(Category).where(Category.slug == "home-office"))
    saved_product = await db_session.scalar(
        select(Product).where(Product.slug == "demo-home-office-01")
    )
    assert saved_category is not None and saved_category.name == "Моя категория"
    assert saved_product is not None
    assert (saved_product.name, saved_product.price, saved_product.stock_quantity) == (
        "Мой товар",
        Decimal("42.00"),
        2,
    )
    assert saved_product.is_active is False
    assert (
        await db_session.scalar(
            select(func.count()).select_from(Product).where(Product.description.is_not(None))
        )
        == 99
    )


async def test_concurrent_seed_runs_do_not_duplicate_records(db_session: AsyncSession) -> None:
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def run() -> tuple[int, int]:
        async with session_factory() as session:
            return await seed_catalog(session)

    results = await asyncio.gather(run(), run())
    assert sum(categories for categories, _ in results) == 5
    assert sum(products for _, products in results) == 100
    assert await db_session.scalar(select(func.count()).select_from(Category)) == 5
    assert await db_session.scalar(select(func.count()).select_from(Product)) == 100
