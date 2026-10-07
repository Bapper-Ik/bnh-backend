"""Durable account-link delivery. Raw bearer links never enter database rows or logs."""

import asyncio
import hashlib
import hmac
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.service import AuditDetails, record_event
from app.core.config import Settings
from app.core.errors import DomainError
from app.identity.models import Account, AccountEmail, LoginAttempt, RecoveryToken
from app.identity.service import digest

logger = logging.getLogger("custodian.account_email")
Sender = Callable[[Settings, AccountEmail, str, str], Awaitable[None]]


def require_delivery(settings: Settings) -> None:
    if not settings.mail_enabled:
        raise DomainError(
            "SERVICE_UNAVAILABLE",
            "Account email is temporarily unavailable. Contact your administrator.",
            503,
        )


def link_token(settings: Settings, token_id: UUID) -> str:
    assert settings.account_link_secret
    # A keyed PRF allows the worker to retry exactly the same message without
    # persisting an unencrypted bearer token. The key lives only in service secrets.
    return hmac.new(
        settings.account_link_secret.get_secret_value().encode(),
        f"custodian-account-link-v1:{token_id}".encode(),
        hashlib.sha256,
    ).hexdigest()


async def take_limit(session: AsyncSession, bucket: str, maximum: int, seconds: int) -> bool:
    now = datetime.now(UTC)
    key = digest(bucket)
    await session.execute(
        insert(LoginAttempt).values(key=key, count=0, window_start=now).on_conflict_do_nothing()
    )
    row = await session.scalar(
        select(LoginAttempt).where(LoginAttempt.key == key).with_for_update()
    )
    assert row
    if now - row.window_start >= timedelta(seconds=seconds):
        row.count, row.window_start = 0, now
    if row.count >= maximum:
        return False
    row.count += 1
    return True


async def queue_link(session: AsyncSession, account: Account, settings: Settings) -> None:
    require_delivery(settings)
    assert settings.frontend_origin and settings.mail_from
    now = datetime.now(UTC)
    await session.execute(
        update(RecoveryToken)
        .where(RecoveryToken.account_id == account.id, RecoveryToken.consumed_at.is_(None))
        .values(consumed_at=now)
    )
    token_id = uuid4()
    token = RecoveryToken(
        id=token_id,
        account_id=account.id,
        purpose="activate" if account.password_pending else "reset",
        token_hash=digest(link_token(settings, token_id)),
        expires_at=now + timedelta(minutes=30),
    )
    session.add(token)
    await session.flush()
    session.add(
        AccountEmail(
            token_id=token.id,
            recipient=account.email,
            sender=str(settings.mail_from),
            link_origin=settings.frontend_origin,
            available_at=now,
        )
    )
    await record_event(
        session, action="auth.email_queued", actor_id=None, resource_id=account.identity_id
    )


async def request_link(session: AsyncSession, email: str, settings: Settings) -> bool:
    require_delivery(settings)
    # A bounded global bucket stops arbitrary addresses from creating unbounded
    # rate-limit rows. Per-address throttling behaves identically for unknown users.
    if not await take_limit(session, "account-link:global", 100, 60):
        return False
    permitted = await take_limit(session, "account-link:" + email.lower(), 3, 3600)
    await record_event(session, action="auth.recovery_requested", actor_id=None)
    if permitted:
        account = await session.scalar(
            select(Account).where(Account.email == email.lower()).with_for_update()
        )
        if account and account.active:
            # Double clicks/resends within a minute do not invalidate the first link.
            recent = await session.scalar(
                select(RecoveryToken.id).where(
                    RecoveryToken.account_id == account.id,
                    RecoveryToken.created_at > datetime.now(UTC) - timedelta(seconds=60),
                    RecoveryToken.consumed_at.is_(None),
                )
            )
            if not recent:
                await queue_link(session, account, settings)
    return True


async def send_resend(settings: Settings, job: AccountEmail, token: str, purpose: str) -> None:
    assert settings.resend_api_key
    subject = (
        "Activate your Custodian account"
        if purpose == "activate"
        else "Reset your Custodian password"
    )
    link = f"{job.link_origin}/recover#token={token}"
    body = f"{subject}\n\nOpen this single-use link within 30 minutes:\n{link}\n\nIf you did not request this, you can ignore this email. Your password has not changed.\n\nCustodian by Brendan"
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": "Bearer " + settings.resend_api_key.get_secret_value(),
                "Idempotency-Key": f"custodian-account-link/{job.id}",
            },
            json={
                "from": f"Custodian <{job.sender}>",
                "to": [job.recipient],
                "subject": subject,
                "text": body,
            },
        )
        # Never propagate provider bodies, credentials, addresses or link payloads.
        if not 200 <= response.status_code < 300:
            raise RuntimeError("Email provider did not accept the message")


async def deliver_one(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, send: Sender = send_resend
) -> bool:
    async with sessions() as session, session.begin():
        now = datetime.now(UTC)
        job = await session.scalar(
            select(AccountEmail)
            .where(AccountEmail.status == "pending", AccountEmail.available_at <= now)
            .order_by(AccountEmail.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return False
        stored = await session.get(RecoveryToken, job.token_id)
        assert stored
        account = await session.scalar(
            select(Account).where(Account.id == stored.account_id).with_for_update()
        )
        stored = await session.scalar(
            select(RecoveryToken)
            .where(RecoveryToken.id == job.token_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert account and stored
        raw = link_token(settings, stored.id)
        if (
            not account.active
            or account.email != job.recipient
            or stored.consumed_at
            or stored.expires_at <= now
            or (stored.purpose == "activate") != account.password_pending
            or not hmac.compare_digest(digest(raw), stored.token_hash)
        ):
            job.status = "cancelled"
            await record_event(
                session,
                action="auth.email_cancelled",
                actor_id=None,
                resource_id=account.identity_id,
            )
            return True
        job.attempts += 1
        try:
            await send(settings, job, raw, stored.purpose)
        except Exception:
            job.status = "failed" if job.attempts >= 6 else "pending"
            job.available_at = now + timedelta(seconds=min(30 * 2 ** (job.attempts - 1), 600))
            await record_event(
                session,
                action="auth.email_failed",
                actor_id=None,
                resource_id=account.identity_id,
                details=AuditDetails(outcome="denied"),
            )
            logger.warning("account_email.delivery_failed")
        else:
            job.status, job.accepted_at = "accepted", datetime.now(UTC)
            await record_event(
                session,
                action="auth.email_accepted",
                actor_id=None,
                resource_id=account.identity_id,
            )
        return True


async def delivery_loop(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, send: Sender = send_resend
) -> None:
    while True:
        try:
            worked = await deliver_one(sessions, settings, send)
        except Exception:
            logger.error("account_email.worker_failed")
            worked = False
        await asyncio.sleep(0.5 if worked else 2)
