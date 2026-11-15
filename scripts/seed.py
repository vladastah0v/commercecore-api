import argparse
import asyncio
import sys
from decimal import Decimal

import asyncpg
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.database import create_database_engine
from app.modules.catalog.models import Category, Product

CATEGORIES = (
    ("home-office", "Домашний офис", "Настольная лампа", "лампа", "2490.00"),
    ("kitchen", "Кухня", "Термокружка", "термокружка", "1290.00"),
    ("travel", "Путешествия", "Дорожный рюкзак", "рюкзак", "3990.00"),
    ("fitness", "Фитнес", "Коврик для тренировок", "коврик", "1890.00"),
    ("stationery", "Канцелярия", "Блокнот", "блокнот", "490.00"),
)


async def seed_catalog(session: AsyncSession) -> tuple[int, int]:
    """Add missing demo records without changing existing catalog entries."""
    async with session.begin():
        category_result = await session.execute(
            insert(Category)
            .values([{"slug": slug, "name": name} for slug, name, *_ in CATEGORIES])
            .on_conflict_do_nothing(index_elements=[Category.slug])
            .returning(Category.id)
        )
        category_count = len(category_result.scalars().all())
        rows = await session.execute(
            select(Category.slug, Category.id).where(
                Category.slug.in_([slug for slug, *_ in CATEGORIES])
            )
        )
        category_ids = dict(rows.all())
        products = []
        for slug, name, product_name, product_kind, base_price in CATEGORIES:
            for number in range(1, 21):
                products.append(
                    {
                        "category_id": category_ids[slug],
                        "name": f"{product_name} «Модель {number:02d}»",
                        "slug": f"demo-{slug}-{number:02d}",
                        "description": (
                            f"Демонстрационный товар: {product_kind}, модель {number:02d}. "
                            f"Категория: {name}."
                        ),
                        "price": Decimal(base_price) + Decimal(number - 1) * Decimal("75.00"),
                        "stock_quantity": 5 + number,
                        "is_active": True,
                    }
                )
        product_result = await session.execute(
            insert(Product)
            .values(products)
            .on_conflict_do_nothing(index_elements=[Product.slug])
            .returning(Product.id)
        )
        product_count = len(product_result.scalars().all())
    return category_count, product_count


async def run_seed() -> tuple[int, int]:
    engine = create_database_engine(get_settings())
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            return await seed_catalog(session)
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Add synthetic demo catalog data.")
    parser.parse_args()
    try:
        categories, products = asyncio.run(run_seed())
    except (SQLAlchemyError, asyncpg.PostgresError, OSError):
        print("Database operation failed. Check the connection and migrations.", file=sys.stderr)
        return 1
    print(f"Created {categories} categories and {products} products.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
