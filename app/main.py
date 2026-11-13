import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.core.database import create_database_engine
from app.core.exceptions import register_exception_handlers
from app.core.health import check_postgres, check_redis
from app.core.redis import create_redis_client
from app.modules.auth.router import router as auth_router
from app.modules.catalog.router import router as catalog_router
from app.modules.users.router import router as users_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_database_engine(settings)
    try:
        redis = create_redis_client(settings)
        try:
            app.state.db_engine = engine
            app.state.db_session_factory = async_sessionmaker(engine, expire_on_commit=False)
            app.state.redis = redis
            yield
        finally:
            await redis.aclose()
    finally:
        await engine.dispose()


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", debug=settings.debug, lifespan=lifespan)
register_exception_handlers(app)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(catalog_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")


@app.get("/api/v1/health", tags=["health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/health/ready", tags=["health"])
async def readiness_check(request: Request) -> JSONResponse:
    postgres_ok, redis_ok = await asyncio.gather(
        check_postgres(request.app.state.db_engine),
        check_redis(request.app.state.redis),
    )
    ready = postgres_ok and redis_ok
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ok" if ready else "unavailable",
            "services": {
                "postgres": "ok" if postgres_ok else "unavailable",
                "redis": "ok" if redis_ok else "unavailable",
            },
        },
    )
