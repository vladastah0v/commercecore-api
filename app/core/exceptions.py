import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.modules.auth.exceptions import (
    AuthenticationRequiredError,
    EmailAlreadyRegisteredError,
    InsufficientPermissionsError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
)
from app.modules.catalog.exceptions import (
    CategoryNotFoundError,
    CategorySlugConflictError,
    ProductNotFoundError,
    ProductSlugConflictError,
)

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProductNotFoundError)
    async def handle_product_not_found(
        request: Request, error: ProductNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(ProductSlugConflictError)
    async def handle_product_slug_conflict(
        request: Request, error: ProductSlugConflictError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(CategoryNotFoundError)
    async def handle_category_not_found(
        request: Request, error: CategoryNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(CategorySlugConflictError)
    async def handle_category_slug_conflict(
        request: Request, error: CategorySlugConflictError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(AuthenticationRequiredError)
    async def handle_authentication_required(
        request: Request, error: AuthenticationRequiredError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"detail": str(error)},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(InsufficientPermissionsError)
    async def handle_insufficient_permissions(
        request: Request, error: InsufficientPermissionsError
    ) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(error)})

    @app.exception_handler(InvalidRefreshTokenError)
    async def handle_invalid_refresh_token(
        request: Request, error: InvalidRefreshTokenError
    ) -> JSONResponse:
        return JSONResponse(status_code=401, content={"detail": str(error)})

    @app.exception_handler(InvalidCredentialsError)
    async def handle_invalid_credentials(
        request: Request, error: InvalidCredentialsError
    ) -> JSONResponse:
        return JSONResponse(status_code=401, content={"detail": str(error)})

    @app.exception_handler(EmailAlreadyRegisteredError)
    async def handle_duplicate_email(
        request: Request, error: EmailAlreadyRegisteredError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(error)},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        details = [
            {key: item[key] for key in ("type", "loc", "msg") if key in item}
            for item in error.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": details})

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, error: SQLAlchemyError) -> JSONResponse:
        logger.error("Database operation failed", extra={"error_type": type(error).__name__})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )
