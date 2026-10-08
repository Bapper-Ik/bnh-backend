from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.service import request_scope
from app.audit.models import AuditEvent
from app.audit.read import board_requests
from app.core.database import get_session
from app.history.filters import RequestFilters
from app.identity.service import Actor, current_actor
from app.organisation.models import Department, Entity, Membership
from app.organisation.service import has_approval_office
from app.requisitions.models import Requisition, Revision
from app.requisitions.router import Page, list_requests

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])
STATES = (
    "DRAFT",
    "PENDING_AUTHORITY",
    "AWAITING_BOARD_RESOLUTION",
    "AWAITING_CHAIRMAN_SIGNOFF",
    "RETURNED_FOR_REVISION",
    "APPROVED",
    "REJECTED",
    "DEFERRED",
    "CONDITIONALLY_APPROVED",
)
PUBLIC_EVENTS = {
    "requisition.created": "Draft created",
    "requisition.updated": "Draft updated",
    "requisition.revision_created": "Correction started",
    "requisition.submitted": "Requisition submitted",
    "requisition.approved": "Requisition approved",
    "requisition.rejected": "Requisition rejected",
    "requisition.returned": "Returned for revision",
    "board.confirmed": "Board outcome confirmed",
}
BOARD_EVENTS = {
    "board.recorded": "Board resolution recorded",
    "board.returned": "Board record returned to Secretary",
}


class DashboardCount(BaseModel):
    state: str
    count: int


class DashboardActivity(BaseModel):
    id: UUID
    request_id: UUID
    reference: str
    label: str
    at: datetime


class DashboardView(BaseModel):
    counts: list[DashboardCount]
    total: int
    own_requests: int
    can_create: bool
    can_access_approval_inbox: bool
    tasks: Page
    recent_requests: Page
    activity: list[DashboardActivity]
    refreshed_at: datetime


@router.get("", response_model=DashboardView)
async def dashboard(
    response: Response,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> DashboardView:
    rows = (
        await s.execute(
            select(
                Requisition.state,
                func.count(),
                func.count().filter(Requisition.requester_id == actor.id),
            )
            .outerjoin(Revision, Revision.id == Requisition.current_revision_id)
            .where(request_scope(actor))
            .group_by(Requisition.state)
        )
    ).all()
    counts = {state: count for state, count, _ in rows}
    events = (
        await s.execute(
            select(
                AuditEvent.id,
                AuditEvent.action,
                AuditEvent.created_at,
                Requisition.id,
                Requisition.reference,
            )
            .join(Requisition, Requisition.id == AuditEvent.resource_id)
            .outerjoin(Revision, Revision.id == Requisition.current_revision_id)
            .where(
                request_scope(actor),
                or_(
                    AuditEvent.action.in_(PUBLIC_EVENTS),
                    AuditEvent.action.in_(BOARD_EVENTS) & Requisition.id.in_(board_requests(actor)),
                ),
            )
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(10)
        )
    ).all()
    can_create = not actor.account.read_only and bool(
        await s.scalar(
            select(Membership.id)
            .join(Department, Department.id == Membership.department_id)
            .join(Entity, Entity.id == Membership.entity_id)
            .where(
                Membership.identity_id == actor.id,
                Membership.active.is_(True),
                Department.active.is_(True),
                Entity.active.is_(True),
            )
            .limit(1)
        )
    )
    can_inbox = await has_approval_office(s, actor.id)
    tasks = (
        await list_requests(RequestFilters(inbox=True, limit=5), actor, s)
        if can_inbox
        else Page(items=[], total=0, limit=5, offset=0)
    )
    response.headers["Cache-Control"] = "no-store"
    return DashboardView(
        counts=[DashboardCount(state=state, count=counts.get(state, 0)) for state in STATES],
        total=sum(counts.values()),
        own_requests=sum(own for _, _, own in rows),
        can_create=can_create,
        can_access_approval_inbox=can_inbox,
        tasks=tasks,
        recent_requests=await list_requests(RequestFilters(limit=5), actor, s),
        activity=[
            DashboardActivity(
                id=event_id,
                request_id=request_id,
                reference=reference,
                label={**PUBLIC_EVENTS, **BOARD_EVENTS}[action],
                at=at,
            )
            for event_id, action, at, request_id, reference in events
        ],
        refreshed_at=datetime.now(UTC),
    )
