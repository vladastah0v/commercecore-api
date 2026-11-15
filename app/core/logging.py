import json
import logging
import sys
from datetime import UTC, datetime
from time import perf_counter

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_FIELDS = ("method", "route", "status_code", "duration_ms", "error_type")
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
logger = logging.getLogger("app.http")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _FIELDS:
            if hasattr(record, field):
                data[field] = getattr(record, field)
        return json.dumps(data, ensure_ascii=False)


class SafeUvicornErrorFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.msg == "Exception in ASGI application\n":
            # The request middleware logs the exception type without its potentially sensitive text.
            record.exc_info = None
            record.exc_text = None
        return True


def configure_logging() -> None:
    app_logger = logging.getLogger("app")
    if not any(getattr(handler, "_commercecore_json", False) for handler in app_logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JsonFormatter())
        handler._commercecore_json = True
        app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)
    # Uvicorn's default access log contains the raw path and query string.
    logging.getLogger("uvicorn.access").disabled = True
    error_logger = logging.getLogger("uvicorn.error")
    if not any(isinstance(item, SafeUvicornErrorFilter) for item in error_logger.filters):
        error_logger.addFilter(SafeUvicornErrorFilter())


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = perf_counter()
        status_code = 500
        error_type = None

        async def send_with_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        except Exception as error:
            error_type = type(error).__name__
            raise
        finally:
            route = scope.get("route")
            method = scope.get("method", "")
            fields = {
                "method": method if method in _METHODS else "OTHER",
                "route": getattr(route, "path", "<unmatched>"),
                "status_code": status_code,
                "duration_ms": round((perf_counter() - started) * 1000, 2),
            }
            if error_type:
                fields["error_type"] = error_type
            logger.log(
                logging.ERROR if error_type or status_code >= 500 else logging.INFO,
                "HTTP request completed",
                extra=fields,
            )
