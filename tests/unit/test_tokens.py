from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from app.core.config import Settings
from app.core.tokens import (
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
)


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, jwt_secret="test-only-secret-" * 3)


def test_access_and_refresh_tokens_are_distinct_and_typed(settings: Settings) -> None:
    user_id = uuid4()
    access = create_access_token(user_id, settings)
    refresh = create_refresh_token(user_id, settings)
    access_claims = decode_token(access, "access", settings)
    refresh_claims = decode_token(refresh, "refresh", settings)

    assert access_claims.user_id == refresh_claims.user_id == user_id
    assert access_claims.token_id != refresh_claims.token_id
    assert access_claims.expires_at < refresh_claims.expires_at
    with pytest.raises(InvalidTokenError):
        decode_token(refresh, "access", settings)
    with pytest.raises(InvalidTokenError):
        decode_token(access, "refresh", settings)


def test_expired_or_tampered_token_is_rejected(settings: Settings) -> None:
    now = datetime.now(UTC)
    expired = jwt.encode(
        {
            "sub": str(uuid4()),
            "jti": str(uuid4()),
            "type": "access",
            "iat": now - timedelta(minutes=2),
            "exp": now - timedelta(minutes=1),
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    wrong_key = jwt.encode(
        {
            "sub": str(uuid4()),
            "jti": str(uuid4()),
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=1),
        },
        "different-secret-" * 3,
        algorithm="HS256",
    )
    for token in (expired, wrong_key, "not-a-token"):
        with pytest.raises(InvalidTokenError):
            decode_token(token, "access", settings)


@pytest.mark.parametrize("claim", ["sub", "jti", "type", "iat", "exp"])
def test_missing_required_claim_is_rejected(settings: Settings, claim: str) -> None:
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid4()),
        "jti": str(uuid4()),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=1),
    }
    del payload[claim]
    token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        decode_token(token, "access", settings)


@pytest.mark.parametrize("secret", [None, "short"])
def test_missing_or_short_secret_prevents_token_creation(secret: str | None) -> None:
    settings = Settings(_env_file=None, jwt_secret=secret)
    with pytest.raises(ValueError, match="COMMERCECORE_JWT_SECRET"):
        create_access_token(uuid4(), settings)
