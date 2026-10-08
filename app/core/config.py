from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import EmailStr, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


def normalize_database_url(value: str) -> str:
    """Accept Render PostgreSQL URLs with the asynchronous driver used by the app."""
    url = make_url(value)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+asyncpg")
    return url.render_as_string(hide_password=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    environment: Literal["development", "test", "production"] = "development"
    database_url: SecretStr
    allowed_origins: list[str] = ["http://localhost:5173"]
    database_ssl: bool = True
    cookie_secure: bool = True
    session_hours: int = Field(default=8, ge=1, le=24)
    mail_enabled: bool = False
    mail_from: EmailStr | None = None
    resend_api_key: SecretStr | None = None
    account_link_secret: SecretStr | None = None
    frontend_origin: str | None = None
    cloudinary_url: SecretStr | None = None
    cloudinary_cloud_name: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]+$")
    cloudinary_api_key: SecretStr | None = None
    cloudinary_api_secret: SecretStr | None = None
    attachment_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=10 * 1024 * 1024)
    attachment_max_count: int = Field(default=10, ge=1, le=20)
    signing_minutes: int = Field(default=5, ge=1, le=15)

    @field_validator("database_url", mode="before")
    @classmethod
    def database_driver(cls, value: str | SecretStr) -> SecretStr:
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        return SecretStr(normalize_database_url(raw))

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
        if self.cloudinary_url:
            from urllib.parse import unquote

            cloud = urlsplit(self.cloudinary_url.get_secret_value())
            if (
                cloud.scheme != "cloudinary"
                or not cloud.hostname
                or not cloud.username
                or not cloud.password
                or cloud.query
                or cloud.fragment
                or cloud.path not in {"", "/"}
            ):
                raise ValueError("CLOUDINARY_URL must contain a cloud name, API key and API secret")
            if not self.cloudinary_cloud_name:
                self.cloudinary_cloud_name = cloud.hostname
            if not self.cloudinary_api_key:
                self.cloudinary_api_key = SecretStr(unquote(cloud.username))
            if not self.cloudinary_api_secret:
                self.cloudinary_api_secret = SecretStr(unquote(cloud.password))
        if self.cloudinary_cloud_name and not all(
            c.isalnum() or c in "-_" for c in self.cloudinary_cloud_name
        ):
            raise ValueError("Invalid Cloudinary cloud name")
        if self.mail_enabled:
            if (
                not self.mail_from
                or not self.resend_api_key
                or not self.resend_api_key.get_secret_value().strip()
            ):
                raise ValueError("Enabled email requires MAIL_FROM and RESEND_API_KEY")
            if (
                not self.account_link_secret
                or len(self.account_link_secret.get_secret_value()) < 32
            ):
                raise ValueError("ACCOUNT_LINK_SECRET must contain at least 32 random characters")
            origin = urlsplit(self.frontend_origin or "")
            if (
                self.frontend_origin not in self.allowed_origins
                or origin.scheme not in {"http", "https"}
                or not origin.netloc
                or origin.username
                or origin.password
                or origin.path
                or origin.query
                or origin.fragment
                or (origin.scheme == "http" and origin.hostname not in {"localhost", "127.0.0.1"})
            ):
                raise ValueError(
                    "FRONTEND_ORIGIN must be an exact trusted origin (HTTPS except loopback)"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
