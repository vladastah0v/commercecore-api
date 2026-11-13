from fastapi import Request
from redis.asyncio import Redis

from app.core.config import Settings


def create_redis_client(settings: Settings) -> Redis:
    return Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        socket_connect_timeout=3,
        socket_timeout=3,
        decode_responses=True,
    )


def get_redis(request: Request) -> Redis:
    return request.app.state.redis
