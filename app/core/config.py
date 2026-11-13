from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="COMMERCECORE_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "CommerceCore API"
    debug: bool = False
    jwt_secret: SecretStr | None = None
    access_token_minutes: int = Field(default=15, ge=1)
    refresh_token_days: int = Field(default=30, ge=1)
    postgres_host: str = "127.0.0.1"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_user: str = Field(default="commercecore", validation_alias="POSTGRES_USER")
    postgres_password: SecretStr = Field(
        default=SecretStr(""), validation_alias="POSTGRES_PASSWORD"
    )
    postgres_db: str = Field(default="commercecore", validation_alias="POSTGRES_DB")
    redis_host: str = "127.0.0.1"
    redis_port: int = Field(default=6379, ge=1, le=65535)


@lru_cache
def get_settings() -> Settings:
    return Settings()
