import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import app.main as main
from app.core.config import Settings

pytestmark = pytest.mark.skipif(
    os.getenv("COMMERCECORE_RUN_INFRA_TESTS") != "1",
    reason="Set COMMERCECORE_RUN_INFRA_TESTS=1 and start the dedicated test services",
)


@pytest_asyncio.fixture
async def test_client(monkeypatch):
    monkeypatch.setenv("POSTGRES_USER", "commercecore_test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-only-password")
    monkeypatch.setenv("POSTGRES_DB", "commercecore_test")
    monkeypatch.setenv("COMMERCECORE_POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("COMMERCECORE_POSTGRES_PORT", "55432")
    monkeypatch.setenv("COMMERCECORE_REDIS_HOST", "127.0.0.1")
    monkeypatch.setenv("COMMERCECORE_REDIS_PORT", "56379")
    settings = Settings(_env_file=None)
    monkeypatch.setattr(main, "get_settings", lambda: settings)

    async with main.app.router.lifespan_context(main.app):
        async with AsyncClient(
            transport=ASGITransport(app=main.app), base_url="http://test"
        ) as client:
            yield client


async def test_application_connects_to_test_services(test_client) -> None:
    response = await test_client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "services": {"postgres": "ok", "redis": "ok"},
    }


async def test_session_uses_separate_test_database(test_client) -> None:
    async with main.app.state.db_session_factory() as session:
        database_name = await session.scalar(text("SELECT current_database()"))

    assert database_name == "commercecore_test"
