import ipaddress
from hashlib import sha256
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings, get_settings
from app.core.redis import get_redis

_INCREMENT_WITH_EXPIRY = """
local count = redis.call('INCR', KEYS[1])
if count == 1 or redis.call('TTL', KEYS[1]) < 0 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return {count, redis.call('TTL', KEYS[1])}
"""


def login_rate_key(host: str) -> str:
    address = ipaddress.ip_address(host)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    digest = sha256(str(address).encode("ascii")).hexdigest()
    return f"commercecore:login-rate:{digest}"


async def check_login_rate_limit(
    request: Request,
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    try:
        if request.client is None:
            raise ValueError("Client address is missing")
        key = login_rate_key(request.client.host)
        count, ttl = await redis.eval(
            _INCREMENT_WITH_EXPIRY, 1, key, settings.login_rate_window_seconds
        )
    except (RedisError, OSError, TimeoutError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Login temporarily unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from None
    if count > settings.login_rate_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(max(1, ttl)), "Cache-Control": "no-store"},
        )
