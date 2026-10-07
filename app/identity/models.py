from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, Record


class Account(Record, Base):
    __tablename__ = "accounts"
    identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.identities.id", ondelete="RESTRICT"), unique=True
    )
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True, server_default="true")
    password_pending: Mapped[bool] = mapped_column(default=False, server_default="false")
    read_only: Mapped[bool] = mapped_column(default=False, server_default="false")
    permissions: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")


class LoginSession(Record, Base):
    __tablename__ = "login_sessions"
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.accounts.id", ondelete="RESTRICT")
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(default=False, server_default="false")


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RecoveryToken(Record, Base):
    __tablename__ = "recovery_tokens"
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.accounts.id", ondelete="RESTRICT")
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    purpose: Mapped[str] = mapped_column(default="reset", server_default="reset")
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccountEmail(Record, Base):
    __tablename__ = "account_emails"
    token_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.recovery_tokens.id", ondelete="RESTRICT"), unique=True
    )
    recipient: Mapped[str] = mapped_column(String(320))
    sender: Mapped[str] = mapped_column(String(320))
    link_origin: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
