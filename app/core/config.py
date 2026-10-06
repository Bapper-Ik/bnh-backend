from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    environment: Literal["development", "test", "production"] = "development"
    database_url: SecretStr
    allowed_origins: list[str] = ["http://localhost:5173"]
    database_ssl: bool = True
    cookie_secure: bool = True
    session_hours: int = 8
    signing_minutes: int = 5

    @model_validator(mode="after")
    def validate_database(self) -> "Settings":
        url = make_url(self.database_url.get_secret_value())
        if url.drivername != "postgresql+asyncpg" or not url.password:
            raise ValueError("A password-authenticated PostgreSQL asyncpg URL is required")
        if not self.allowed_origins or "*" in self.allowed_origins:
            raise ValueError("Explicit trusted origins are required")
        if self.environment == "production":
            if not self.cookie_secure or any(
                not x.startswith("https://") for x in self.allowed_origins
            ):
                raise ValueError("Production requires secure cookies and HTTPS origins")
            if url.password == "REPLACE_ME":
                raise ValueError("Production requires configured database credentials")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
