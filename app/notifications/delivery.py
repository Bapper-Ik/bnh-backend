"""Leased delivery; persist the identical envelope before calling the provider."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
from sqlalchemy import and_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.service import AuditDetails, record_event
from app.core.config import Settings
from app.identity.models import Account
from app.notifications.models import Notification
from app.notifications.service import TEMPLATES, Recipient, href, listing, materialize_one, message
from app.requisitions.models import Requisition

logger = logging.getLogger("custodian.notifications")
Sender = Callable[[Settings, Notification, str], Awaitable[UUID]]


class DeliveryFailure(Exception):
    def __init__(self, code: str, *, retryable: bool = True, retry_after: int = 0):
        self.code, self.retryable, self.retry_after = code, retryable, retry_after
        super().__init__(code)


async def send_resend(settings: Settings, row: Notification, reference: str) -> UUID:
    assert (
        settings.resend_api_key and row.link_origin and row.sender_address and row.recipient_address
    )
    title = TEMPLATES[row.template]
    body = f"{title}\n\n{reference}\n{message(row)}\n\n{row.link_origin}{href(row)}\n\nSign in using your own account. This link cannot approve a requisition.\n\nCustodian by Brendan"
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": "Bearer " + settings.resend_api_key.get_secret_value(),
                "Idempotency-Key": f"custodian-notification/{row.id}/{row.template_version}",
            },
            json={
                "from": f"Custodian <{row.sender_address}>",
                "to": [row.recipient_address],
                "subject": title,
                "text": body,
            },
        )
    if response.status_code == 429:
        try:
            delay = min(max(int(response.headers.get("retry-after", "30")), 1), 3600)
        except ValueError:
            delay = 30
        raise DeliveryFailure("provider_rate_limit", retry_after=delay)
    if response.status_code == 409:
        try:
            conflict = response.json().get("name")
        except (ValueError, AttributeError):
            conflict = None
        if conflict == "invalid_idempotent_request":
            raise DeliveryFailure("provider_idempotency_conflict", retryable=False)
    if response.status_code >= 500 or response.status_code in {408, 409}:
        raise DeliveryFailure("provider_temporary_failure")
    if not 200 <= response.status_code < 300:
        raise DeliveryFailure("provider_rejected", retryable=False)
    try:
        return UUID(str(response.json()["id"]))
    except (KeyError, TypeError, ValueError):
        raise DeliveryFailure("provider_invalid_response") from None


async def claim_email(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    notification_id: UUID | None = None,
) -> tuple[UUID, UUID] | None:
    if not settings.mail_enabled:
        return None
    async with sessions() as s, s.begin():
        now = datetime.now(UTC)
        row = await s.scalar(
            select(Notification)
            .where(
                or_(
                    and_(Notification.email_status == "pending", Notification.available_at <= now),
                    and_(Notification.email_status == "sending", Notification.lease_until <= now),
                )
            )
            .where(Notification.id == notification_id if notification_id else true())
            .order_by(Notification.available_at, Notification.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not row:
            return None
        account = await s.scalar(select(Account).where(Account.identity_id == row.recipient_id))
        assert account
        if row.first_attempt_at is None:
            row.first_attempt_at = now
            row.recipient_address, row.sender_address, row.link_origin = (
                account.email,
                str(settings.mail_from),
                settings.frontend_origin,
            )
        row.email_status = "sending"
        row.lease_until, row.lease_token = now + timedelta(minutes=2), uuid4()
        row.attempts += 1
        return row.id, row.lease_token


def stale_update(row: Notification, req: Requisition) -> bool:
    if row.kind != "request_update":
        return False
    states = {
        "submitted": {
            "PENDING_AUTHORITY",
            "AWAITING_BOARD_RESOLUTION",
            "AWAITING_CHAIRMAN_SIGNOFF",
        },
        "resubmitted": {
            "PENDING_AUTHORITY",
            "AWAITING_BOARD_RESOLUTION",
            "AWAITING_CHAIRMAN_SIGNOFF",
        },
        "approved": {"APPROVED"},
        "rejected": {"REJECTED"},
        "returned": {"RETURNED_FOR_REVISION"},
        "board_approved": {"APPROVED"},
        "board_rejected": {"REJECTED"},
        "board_deferred": {"DEFERRED"},
        "board_conditional": {"CONDITIONALLY_APPROVED"},
    }
    return req.current_revision_id != row.revision_id or req.state not in states.get(
        row.template, set()
    )


async def deliver_claim(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    claim: tuple[UUID, UUID],
    send: Sender = send_resend,
) -> None:
    async with sessions() as s, s.begin():
        initial = await s.get(Notification, claim[0])
        if not initial:
            return
        # Match API lock ordering: recipient account, business object, delivery row.
        account = await s.scalar(
            select(Account)
            .where(Account.identity_id == initial.recipient_id)
            .with_for_update(read=True)
        )
        req = await s.scalar(
            select(Requisition)
            .where(Requisition.id == initial.requisition_id)
            .with_for_update(read=True)
        )
        row = await s.scalar(
            select(Notification)
            .where(Notification.id == claim[0])
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not row or row.email_status != "sending" or row.lease_token != claim[1]:
            return
        assert account and req and row.first_attempt_at
        permitted = (
            account.active
            and not account.password_pending
            and bool(
                (
                    await s.execute(listing(Recipient(account)).where(Notification.id == row.id))
                ).first()
            )
        )
        cancelled = (
            not permitted
            or stale_update(row, req)
            or account.email != row.recipient_address
            or row.sender_address != str(settings.mail_from)
            or row.link_origin != settings.frontend_origin
            or not settings.mail_enabled
        )
        if cancelled:
            row.email_status, row.last_error = "cancelled", "recipient_or_work_changed"
        elif row.first_attempt_at <= datetime.now(UTC) - timedelta(hours=23) or row.attempts > 6:
            # Do not replay an uncertain send beyond Resend's 24-hour deduplication window.
            row.email_status, row.last_error = "failed", "retry_window_exhausted"
        else:
            try:
                row.provider_id = await send(settings, row, req.reference)
            except Exception as exc:
                failure = (
                    exc
                    if isinstance(exc, DeliveryFailure)
                    else DeliveryFailure("transport_failure")
                )
                row.email_status = "pending" if failure.retryable and row.attempts < 6 else "failed"
                row.last_error = failure.code
                row.available_at = datetime.now(UTC) + timedelta(
                    seconds=max(failure.retry_after, min(30 * 2 ** (row.attempts - 1), 600))
                )
                logger.warning("notification.delivery_failed")
            else:
                row.email_status, row.accepted_at, row.last_error = (
                    "accepted",
                    datetime.now(UTC),
                    None,
                )
        row.lease_until, row.lease_token = None, None
        await record_event(
            s,
            action="notification.delivery.success"
            if row.email_status == "accepted"
            else "notification.delivery.failure",
            actor_id=None,
            resource_id=req.id,
            entity_id=req.entity_id,
            details=AuditDetails(
                resource_type="notification",
                notification_id=row.id,
                outcome="success" if row.email_status == "accepted" else "denied",
            ),
        )


async def delivery_loop(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, send: Sender = send_resend
) -> None:
    while True:
        worked = False
        try:
            async with sessions() as s, s.begin():
                worked = await materialize_one(s, settings)
            claim = await claim_email(sessions, settings)
            if claim:
                await deliver_claim(sessions, settings, claim, send)
                worked = True
        except Exception:
            logger.error("notification.worker_failed")
        await asyncio.sleep(0.5 if worked else 2)
