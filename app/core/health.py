import asyncio

from asyncpg import PostgresError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine


async def check_postgres(engine: AsyncEngine) -> bool:
    try:
        async with asyncio.timeout(5):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, PostgresError, OSError, TimeoutError):
        return False
    return True


async def check_redis(client: Redis) -> bool:
    try:
        async with asyncio.timeout(5):
            return bool(await client.ping())
    except (RedisError, OSError, TimeoutError):
        return False
