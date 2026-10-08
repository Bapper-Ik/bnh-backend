from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import AuditDetails, record_event
from app.core.database import get_session
from app.core.errors import DomainError
from app.identity.service import Actor, current_actor
from app.notifications.models import Notification
from app.notifications.service import TEMPLATES, href, listing, message
from app.requisitions.models import Requisition

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])


class NotificationView(BaseModel):
    id: UUID
    event_id: UUID
    title: str
    message: str
    reference: str
    href: str
    created_at: datetime
    read_at: datetime | None
    email_status: str
    attempts: int
    last_error: str | None


class NotificationPage(BaseModel):
    items: list[NotificationView]
    total: int
    unread_total: int
    limit: int
    offset: int
    email_enabled: bool


def present(row: Notification, reference: str) -> NotificationView:
    return NotificationView(
        id=row.id,
        event_id=row.event_id,
        title=TEMPLATES[row.template],
        message=message(row),
        reference=reference,
        href=href(row),
        created_at=row.created_at,
        read_at=row.read_at,
        email_status=row.email_status,
        attempts=row.attempts,
        last_error=row.last_error,
    )


@router.get("", response_model=NotificationPage)
async def notifications(
    request: Request,
    unread: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=2147483647),
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> NotificationPage:
    query = listing(actor)
    total, unread_total = (
        await s.execute(
            query.with_only_columns(
                func.count(),
                func.count().filter(Notification.read_at.is_(None)),
                maintain_column_froms=True,
            )
        )
    ).one()
    if unread:
        query = query.where(Notification.read_at.is_(None))
        total = unread_total
    rows = (
        await s.execute(
            query.order_by(Notification.created_at.desc(), Notification.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return NotificationPage(
        items=[present(row, reference) for row, reference in rows],
        total=total,
        unread_total=unread_total,
        limit=limit,
        offset=offset,
        email_enabled=request.app.state.settings.mail_enabled,
    )


@router.post("/{notification_id}/read", response_model=NotificationView)
async def mark_read(
    notification_id: UUID,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> NotificationView:
    match = (
        await s.execute(
            listing(actor)
            .where(Notification.id == notification_id)
            .with_for_update(of=Notification)
        )
    ).first()
    if not match:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Notification not found.", 404)
    row, reference = match
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
        await record_event(
            s,
            action="notification.read.success",
            actor_id=actor.id,
            resource_id=row.requisition_id,
            entity_id=await s.scalar(
                select(Requisition.entity_id).where(Requisition.id == row.requisition_id)
            ),
            details=AuditDetails(resource_type="notification", notification_id=row.id),
        )
    return present(row, reference)
