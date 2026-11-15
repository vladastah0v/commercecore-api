import json
import logging
import sys

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import register_exception_handlers
from app.core.logging import (
    JsonFormatter,
    RequestLoggingMiddleware,
    SafeUvicornErrorFilter,
    configure_logging,
)


async def test_requests_log_route_template_without_sensitive_input(caplog) -> None:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.post("/items/{item_id}")
    async def endpoint(item_id: str) -> dict[str, bool]:
        return {"ok": True}

    caplog.set_level(logging.INFO, logger="app.http")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/items/path-secret?token=query-secret",
            headers={"Authorization": "Bearer header-secret"},
            json={"password": "body-secret", "refresh_token": "refresh-secret"},
        )
        assert response.status_code == 200
        assert (await client.get("/missing/path-secret?token=query-secret")).status_code == 404

    records = [record for record in caplog.records if record.name == "app.http"]
    assert len(records) == 2
    first = json.loads(JsonFormatter().format(records[0]))
    assert first["method"] == "POST"
    assert first["route"] == "/items/{item_id}"
    assert first["status_code"] == 200
    assert first["duration_ms"] >= 0
    assert json.loads(JsonFormatter().format(records[1]))["route"] == "<unmatched>"
    output = " ".join(JsonFormatter().format(record) for record in records)
    for secret in ("path-secret", "query-secret", "header-secret", "body-secret", "refresh-secret"):
        assert secret not in output


async def test_database_errors_log_type_without_sql_or_parameters(caplog) -> None:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(app)

    @app.get("/database")
    async def endpoint() -> None:
        raise IntegrityError("sensitive SQL", {"password": "secret-password"}, Exception("private"))

    caplog.set_level(logging.INFO, logger="app")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/database")).status_code == 500
    records = [record for record in caplog.records if record.name.startswith("app.")]
    output = [json.loads(JsonFormatter().format(record)) for record in records]
    assert any(item.get("error_type") == "IntegrityError" for item in output)
    assert any(item.get("status_code") == 500 for item in output)
    assert "secret-password" not in str(output)
    assert "sensitive SQL" not in str(output)


def test_logging_configuration_is_idempotent() -> None:
    app_logger = logging.getLogger("app")
    original_handlers = app_logger.handlers[:]
    original_level = app_logger.level
    access_logger = logging.getLogger("uvicorn.access")
    original_disabled = access_logger.disabled
    error_logger = logging.getLogger("uvicorn.error")
    original_filters = error_logger.filters[:]
    try:
        configure_logging()
        configure_logging()
        handlers = [h for h in app_logger.handlers if getattr(h, "_commercecore_json", False)]
        assert len(handlers) == 1
        assert isinstance(handlers[0].formatter, JsonFormatter)
        assert access_logger.disabled
        assert (
            len([item for item in error_logger.filters if isinstance(item, SafeUvicornErrorFilter)])
            == 1
        )
    finally:
        app_logger.handlers = original_handlers
        app_logger.setLevel(original_level)
        access_logger.disabled = original_disabled
        error_logger.filters = original_filters


def test_uvicorn_asgi_error_hides_exception_details() -> None:
    try:
        raise RuntimeError("secret-token")
    except RuntimeError:
        record = logging.getLogger("uvicorn.error").makeRecord(
            "uvicorn.error",
            logging.ERROR,
            __file__,
            1,
            "Exception in ASGI application\n",
            (),
            sys.exc_info(),
        )
    assert SafeUvicornErrorFilter().filter(record)
    assert "secret-token" not in logging.Formatter().format(record)
