"""Operator-assisted recovery. No public token issuance or pretend mail delivery."""

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.audit.service import AuditDetails, record_event
from app.core.errors import DomainError
from app.identity.models import Account, LoginSession, RecoveryToken
from app.identity.service import digest, hasher


async def revoke_sessions(session: AsyncSession, account: Account, actor_id: UUID | None) -> None:
    # Callers hold an exclusive Account lock, also used by authenticated mutations.
    await session.execute(
        update(LoginSession).where(LoginSession.account_id == account.id).values(revoked=True)
    )
    await record_event(
        session, action="auth.sessions_revoked", actor_id=actor_id, resource_id=account.identity_id
    )


async def issue_recovery(session: AsyncSession, email: str) -> str:
    """Trusted configuration-operator CLI only; never expose as public sign-up."""
    account = await session.scalar(
        select(Account).where(Account.email == email.lower()).with_for_update()
    )
    if not account or not account.active:
        raise DomainError(
            "RESOURCE_NOT_AVAILABLE", "No active account is available for recovery.", 404
        )
    now = datetime.now(UTC)
    await session.execute(
        update(RecoveryToken)
        .where(RecoveryToken.account_id == account.id, RecoveryToken.consumed_at.is_(None))
        .values(consumed_at=now)
    )
    token = secrets.token_urlsafe(48)
    session.add(
        RecoveryToken(
            account_id=account.id, token_hash=digest(token), expires_at=now + timedelta(minutes=30)
        )
    )
    await record_event(
        session, action="auth.recovery_issued", actor_id=None, resource_id=account.identity_id
    )
    return token


async def recover(session: AsyncSession, token: str, password: str) -> bool:
    # Resolve the account without locking first, then use the same Account -> token
    # lock order as issuance and authenticated account mutations.
    account_id = await session.scalar(
        select(RecoveryToken.account_id).where(RecoveryToken.token_hash == digest(token))
    )
    account = (
        await session.scalar(select(Account).where(Account.id == account_id).with_for_update())
        if account_id
        else None
    )
    stored = (
        await session.scalar(
            select(RecoveryToken).where(RecoveryToken.token_hash == digest(token)).with_for_update()
        )
        if account
        else None
    )
    now = datetime.now(UTC)
    if (
        not account
        or not account.active
        or not stored
        or stored.consumed_at
        or stored.expires_at <= now
    ):
        await record_event(
            session,
            action="auth.recovery_failed",
            actor_id=None,
            details=AuditDetails(outcome="denied"),
        )
        return False
    account.password_hash = await run_in_threadpool(hasher.hash, password)
    await session.execute(
        update(RecoveryToken)
        .where(RecoveryToken.account_id == account.id, RecoveryToken.consumed_at.is_(None))
        .values(consumed_at=now)
    )
    await revoke_sessions(session, account, account.identity_id)
    await record_event(
        session,
        action="auth.recovered",
        actor_id=account.identity_id,
        resource_id=account.identity_id,
    )
    return True
