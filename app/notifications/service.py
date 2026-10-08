import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, exists, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.access.principal import Principal
from app.access.service import request_scope
from app.audit.models import AuditEvent, OutboxItem
from app.audit.read import board_requests
from app.audit.service import AuditDetails, record_event
from app.board.models import ChairmanDecision, Resolution
from app.core.config import Settings
from app.identity.models import Account
from app.notifications.models import Notification
from app.requisitions.models import Requisition, Revision

TEMPLATES = {
    "submitted": "Requisition submitted",
    "resubmitted": "Requisition resubmitted",
    "approval_required": "Requisition needs your review",
    "approved": "Requisition approved",
    "rejected": "Requisition rejected",
    "returned": "Requisition returned for revision",
    "board_record_required": "Board resolution needs recording",
    "board_review_required": "Board record needs your review",
    "board_returned": "Board record returned for correction",
    "board_approved": "Board approval confirmed",
    "board_rejected": "Board rejection confirmed",
    "board_deferred": "Board deferment confirmed",
    "board_conditional": "Conditional Board approval confirmed — on hold",
    "board_later_required": "Later Board resolution required — hold remains",
}
OUTCOMES = {
    "APPROVE": "board_approved",
    "REJECT": "board_rejected",
    "DEFER": "board_deferred",
    "CONDITIONAL_APPROVE": "board_conditional",
}


@dataclass
class Recipient:
    account: Account

    @property
    def id(self) -> UUID:
        return self.account.identity_id


def visible(actor: Principal) -> ColumnElement[bool]:
    latest_signed = (
        select(Resolution.id)
        .where(Resolution.revision_id == Revision.id, Resolution.signature != {})
        .order_by(Resolution.number.desc())
        .limit(1)
        .correlate(Revision)
        .scalar_subquery()
    )
    # Correlate Board eligibility to this notification's request. A global Board
    # scan repeated in each OR branch makes background polling unnecessarily costly.
    board = exists(
        board_requests(actor)
        .where(Requisition.id == Notification.requisition_id)
        .correlate(Notification)
    )
    task = and_(
        Notification.revision_id == Requisition.current_revision_id,
        request_scope(actor, inbox=True),
        or_(
            and_(Notification.kind == "approval_task", Revision.approver_id == actor.id),
            and_(
                board,
                or_(
                    and_(
                        Notification.kind == "board_signoff_task",
                        Revision.context["route"]["chairman_id"].astext == str(actor.id),
                        ~exists(
                            select(ChairmanDecision.id).where(
                                ChairmanDecision.resolution_id == Notification.resolution_id
                            )
                        ),
                    ),
                    and_(
                        Notification.kind == "board_record_task",
                        Revision.context["route"]["secretary_id"].astext == str(actor.id),
                        or_(
                            and_(Notification.resolution_id.is_(None), latest_signed.is_(None)),
                            Notification.resolution_id == latest_signed,
                        ),
                    ),
                ),
            ),
        ),
    )
    return and_(
        Notification.recipient_id == actor.id,
        # Own requester updates and scoped inbox work each already establish request access.
        or_(
            and_(Notification.kind == "request_update", Requisition.requester_id == actor.id), task
        ),
    )


def listing(actor: Principal):  # type: ignore[no-untyped-def]
    return (
        select(Notification, Requisition.reference)
        .join(Requisition, Requisition.id == Notification.requisition_id)
        .outerjoin(Revision, Revision.id == Requisition.current_revision_id)
        .where(visible(actor))
    )


def href(row: Notification) -> str:
    return f"/requisitions/{row.requisition_id}" + (
        "/board" if row.kind.startswith("board_") else ""
    )


def message(row: Notification) -> str:
    if row.kind == "request_update":
        return "Open the requisition to view the recorded update and its current status. Approved means authorised, not paid."
    return "Open the assigned work to review the current record. Reading this alert does not approve or sign anything."


async def materialize_one(
    s: AsyncSession, settings: Settings, event_id: UUID | None = None
) -> bool:
    job = await s.scalar(
        select(OutboxItem)
        .where(
            OutboxItem.destination == "requisition_notification",
            OutboxItem.status == "pending",
            OutboxItem.available_at <= datetime.now(UTC),
            OutboxItem.event_id == event_id if event_id else true(),
        )
        .order_by(OutboxItem.created_at, OutboxItem.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not job:
        return False
    try:
        async with s.begin_nested():
            await project(s, settings, job)
    except Exception:
        # A failed savepoint may expire fields changed near the end of projection.
        await s.refresh(job)
        job.attempts += 1
        job.status = "failed" if job.attempts >= 6 else "pending"
        job.available_at = datetime.now(UTC) + timedelta(
            seconds=min(30 * 2 ** (job.attempts - 1), 600)
        )
        logging.getLogger("custodian.notifications").error("notification.projection_failed")
    return True


async def project(s: AsyncSession, settings: Settings, job: OutboxItem) -> None:
    event = await s.get(AuditEvent, job.event_id)
    assert event
    req = await s.get(Requisition, event.resource_id) if event.resource_id else None
    revision_id = (
        UUID(str(event.details["revision_id"])) if event.details.get("revision_id") else None
    )
    rev = await s.get(Revision, revision_id) if revision_id else None
    candidates: list[tuple[UUID, str, str]] = []
    resolution_id = (
        UUID(str(event.details["resolution_id"])) if event.details.get("resolution_id") else None
    )
    resolution = await s.get(Resolution, resolution_id) if resolution_id else None
    if req and rev and rev.requisition_id == req.id:
        raw_route = rev.context.get("route", {})
        route = raw_route if isinstance(raw_route, dict) else {}
        secretary = UUID(str(route["secretary_id"])) if route.get("secretary_id") else None
        chairman = UUID(str(route["chairman_id"])) if route.get("chairman_id") else None
        key = event.action.removeprefix("requisition.")
        if key in {"submitted", "resubmitted"}:
            candidates.append((req.requester_id, "request_update", key))
            if rev.authority == "board" and secretary:
                candidates.append((secretary, "board_record_task", "board_record_required"))
            elif rev.approver_id:
                candidates.append((rev.approver_id, "approval_task", "approval_required"))
        elif key in {"approved", "rejected", "returned"}:
            candidates.append((req.requester_id, "request_update", key))
        elif resolution and resolution.revision_id == rev.id:
            if event.action == "board.recorded" and chairman:
                candidates.append((chairman, "board_signoff_task", "board_review_required"))
            elif event.action == "board.returned" and secretary:
                candidates.append((secretary, "board_record_task", "board_returned"))
            elif event.action == "board.confirmed":
                template = OUTCOMES[str(resolution.data["outcome"])]
                candidates.append((req.requester_id, "request_update", template))
                if template in {"board_deferred", "board_conditional"} and secretary:
                    candidates.append((secretary, "board_record_task", "board_later_required"))
        for recipient_id, kind, template in candidates:
            account = await s.scalar(
                select(Account).where(
                    Account.identity_id == recipient_id,
                    Account.active.is_(True),
                    Account.password_pending.is_(False),
                )
            )
            if not account:
                continue
            if await s.scalar(
                select(Notification.id).where(
                    Notification.event_id == event.id,
                    Notification.recipient_id == recipient_id,
                    Notification.kind == kind,
                )
            ):
                continue
            row = Notification(
                event_id=event.id,
                recipient_id=recipient_id,
                requisition_id=req.id,
                revision_id=rev.id,
                resolution_id=resolution_id,
                kind=kind,
                template=template,
                available_at=datetime.now(UTC),
                created_at=event.created_at,
                email_status="pending" if settings.mail_enabled else "disabled",
            )
            s.add(row)
            await s.flush()
            if not (
                await s.execute(listing(Recipient(account)).where(Notification.id == row.id))
            ).first():
                await s.delete(row)
                continue
            if event.created_at < datetime.now(UTC) - timedelta(hours=24):
                row.email_status, row.last_error = "skipped", "historical_event"
            await record_event(
                s,
                action="notification.create.success",
                actor_id=None,
                resource_id=req.id,
                entity_id=req.entity_id,
                details=AuditDetails(resource_type="notification", notification_id=row.id),
            )
    job.status, job.delivered_at = "delivered", datetime.now(UTC)
    job.attempts += 1
