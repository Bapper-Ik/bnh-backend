import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.audit.service import AuditDetails, record_event
from app.core.database import Identity, get_session
from app.core.errors import DomainError
from app.identity.models import Account, LoginAttempt, LoginSession

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))
PERMISSIONS = frozenset(
    {"staff:manage", "organisation:manage", "office_assignment:manage", "audit:read"}
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def verify_password(stored: str, supplied: str) -> bool:
    try:
        return hasher.verify(stored, supplied)
    except (VerificationError, InvalidHashError):
        return False


@dataclass
class Actor:
    account: Account
    identity: Identity
    login_session: LoginSession

    @property
    def id(self) -> UUID:
        return self.identity.id


def require_origin(request: Request) -> None:
    if request.headers.get("origin") not in request.app.state.settings.allowed_origins:
        raise DomainError(
            "ACCESS_DENIED", "Use the trusted application to perform this action.", 403
        )


async def current_actor(
    request: Request, session: AsyncSession = Depends(get_session, scope="function")
) -> Actor:
    token = request.cookies.get("custodian_session", "")
    row = (
        await session.execute(
            select(LoginSession, Account, Identity)
            .join(Account, LoginSession.account_id == Account.id)
            .join(Identity, Account.identity_id == Identity.id)
            .where(
                LoginSession.token_hash == digest(token),
                LoginSession.expires_at > datetime.now(UTC),
                LoginSession.revoked.is_(False),
                Account.active.is_(True),
            )
            .with_for_update(of=Account, read=request.method in {"GET", "HEAD", "OPTIONS"})
        )
    ).one_or_none()
    if row is None:
        raise DomainError("AUTHENTICATION_REQUIRED", "Sign in to continue.", 401)
    auth, account, identity = row
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_origin(request)
        csrf = request.headers.get("x-csrf-token", "")
        if not csrf or not secrets.compare_digest(digest(csrf), auth.csrf_hash):
            raise DomainError(
                "ACCESS_DENIED", "Your session could not verify this action. Reload and retry.", 403
            )
    return Actor(account, identity, auth)


def require_permission(actor: Actor, permission: str) -> None:
    if permission not in PERMISSIONS or permission not in actor.account.permissions:
        raise DomainError("ACCESS_DENIED", "You do not have access to this action.", 403)


async def authenticate(
    session: AsyncSession, email: str, password: str, *, bucket: str | None = None
) -> tuple[Account | None, bool]:
    now = datetime.now(UTC)
    key = digest(bucket or email.lower())
    await session.execute(
        insert(LoginAttempt).values(key=key, count=0, window_start=now).on_conflict_do_nothing()
    )
    attempt = await session.scalar(
        select(LoginAttempt).where(LoginAttempt.key == key).with_for_update()
    )
    assert attempt
    if now - attempt.window_start > timedelta(minutes=15):
        attempt.count, attempt.window_start = 0, now
    if attempt.count >= 5:
        return None, True
    account = await session.scalar(
        select(Account).where(Account.email == email.lower()).with_for_update()
    )
    valid = await run_in_threadpool(
        verify_password, account.password_hash if account else DUMMY_HASH, password
    )
    if not valid or not account or not account.active:
        attempt.count += 1
        await record_event(
            session, action="auth.failed", actor_id=None, details=AuditDetails(outcome="denied")
        )
        return None, False
    attempt.count = 0
    return account, False
