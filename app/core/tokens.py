from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

import jwt

from app.core.config import Settings

TokenType = Literal["access", "refresh"]
ALGORITHM = "HS256"


class InvalidTokenError(Exception):
    pass


@dataclass(frozen=True)
class TokenClaims:
    user_id: UUID
    token_id: UUID
    token_type: TokenType
    expires_at: datetime


def _secret(settings: Settings) -> str:
    secret = settings.jwt_secret.get_secret_value() if settings.jwt_secret else ""
    if len(secret.encode("utf-8")) < 32:
        raise ValueError("COMMERCECORE_JWT_SECRET must contain at least 32 bytes")
    return secret


def _create_token(
    user_id: UUID, token_type: TokenType, lifetime: timedelta, settings: Settings
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "jti": str(uuid4()),
            "type": token_type,
            "iat": now,
            "exp": now + lifetime,
        },
        _secret(settings),
        algorithm=ALGORITHM,
    )


def create_access_token(user_id: UUID, settings: Settings) -> str:
    return _create_token(
        user_id, "access", timedelta(minutes=settings.access_token_minutes), settings
    )


def create_refresh_token(user_id: UUID, settings: Settings) -> str:
    return _create_token(user_id, "refresh", timedelta(days=settings.refresh_token_days), settings)


def decode_token(token: str, expected_type: TokenType, settings: Settings) -> TokenClaims:
    secret = _secret(settings)
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "jti", "type", "iat", "exp"]},
        )
        if claims["type"] != expected_type or any(
            not isinstance(claims[key], int) or isinstance(claims[key], bool)
            for key in ("iat", "exp")
        ):
            raise InvalidTokenError
        return TokenClaims(
            user_id=UUID(claims["sub"]),
            token_id=UUID(claims["jti"]),
            token_type=expected_type,
            expires_at=datetime.fromtimestamp(claims["exp"], UTC),
        )
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError, OverflowError, OSError):
        raise InvalidTokenError from None
