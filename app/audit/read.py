from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import String, and_, cast, exists, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import ReviewGrant
from app.access.principal import Principal
from app.access.service import request_scope
from app.audit.models import AuditEvent
from app.core.database import Identity
from app.evidence.models import Attachment
from app.history.filters import AuditFilters
from app.identity.service import Actor
from app.organisation.models import Entity, Office
from app.organisation.service import eligible_offices
from app.requisitions.models import Requisition, Revision


class AuditRow(BaseModel):
    id: UUID
    action: str
    at: datetime
    actor_id: UUID | None
    actor_name: str
    company: str | None
    outcome: str
    request_id: UUID | None = None
    reference: str | None = None
    attachment_id: UUID | None = None
    attachment_filename: str | None = None
    revision_id: UUID | None = None
    content_digest: str | None = None


class AuditPage(BaseModel):
    items: list[AuditRow]
    total: int
    limit: int
    offset: int
    before: datetime


def visible_requests(actor: Actor):  # type: ignore[no-untyped-def]
    return (
        select(Requisition.id)
        .outerjoin(Revision, Revision.id == Requisition.current_revision_id)
        .where(request_scope(actor, include_oversight=False))
    )


def board_requests(actor: Principal):  # type: ignore[no-untyped-def]
    route = Revision.context["route"]
    conditions = []
    # Mirror Board document access: both frozen appointments must still be unique and eligible.
    for role in ("secretary", "chairman"):
        current = eligible_offices().where(
            Office.entity_id == Requisition.entity_id, Office.role == role
        )
        count = (
            select(func.count())
            .select_from(current.correlate(Requisition).subquery())
            .scalar_subquery()
        )
        matches = exists(
            current.where(cast(Office.identity_id, String) == route[role + "_id"].astext).correlate(
                Requisition, Revision
            )
        )
        conditions.extend([count == 1, matches])
    return (
        select(Requisition.id)
        .join(Revision, Revision.id == Requisition.current_revision_id)
        .where(
            Revision.authority == "board",
            or_(
                route["secretary_id"].astext == str(actor.id),
                route["chairman_id"].astext == str(actor.id),
            ),
            route["secretary_id"].astext != route["chairman_id"].astext,
            route["chairman_id"].astext != cast(Requisition.requester_id, String),
            literal(not actor.account.read_only),
            *conditions,
        )
    )


async def search_events(s: AsyncSession, actor: Actor, filters: AuditFilters) -> AuditPage:
    requests = visible_requests(actor)
    board = board_requests(actor)
    # Only attachment-domain events may resolve an attachment UUID; an unrelated resource UUID is never reinterpreted as evidence.
    query = (
        select(
            AuditEvent,
            Identity.display_name,
            Entity.name,
            Requisition.id,
            Requisition.reference,
            Attachment.id,
            Attachment.filename,
            Attachment.detached,
        )
        .outerjoin(Identity, Identity.id == AuditEvent.actor_id)
        .outerjoin(Entity, Entity.id == AuditEvent.entity_id)
        .outerjoin(
            Attachment,
            and_(
                AuditEvent.resource_id == Attachment.id,
                AuditEvent.details["resource_type"].astext == "evidence",
            ),
        )
        .outerjoin(
            Requisition,
            or_(
                and_(
                    AuditEvent.resource_id == Requisition.id,
                    AuditEvent.details["resource_type"].astext.in_(
                        ["requisition", "board", "signature", "notification"]
                    ),
                ),
                Requisition.id == Attachment.requisition_id,
            ),
        )
    )
    private_board_event = or_(
        AuditEvent.details["resource_type"].astext == "board",
        AuditEvent.details["resolution_id"].astext.is_not(None),
        Attachment.kind == "board_resolution",
    )
    business_scope = and_(
        Requisition.id.in_(requests),
        or_(
            ~func.coalesce(private_board_event, False),
            AuditEvent.action == "board.confirmed",
            Requisition.id.in_(board),
        ),
    )
    # Entity-wide operational metadata requires an explicit review grant; ordinary membership/admin capability is insufficient.
    grants = select(ReviewGrant.entity_id).where(
        ReviewGrant.identity_id == actor.id,
        ReviewGrant.active.is_(True),
        literal(actor.account.read_only),
    )
    entity_scope = and_(
        AuditEvent.entity_id.in_(grants),
        AuditEvent.details["resource_type"].astext.in_(
            ["organisation", "office", "vendor", "access"]
        ),
    )
    own_security = and_(
        AuditEvent.actor_id == actor.id,
        AuditEvent.entity_id.is_(None),
        AuditEvent.resource_id.is_(None),
        AuditEvent.details["resource_type"].astext.in_(["auth", "audit", "access"]),
    )
    # Reading the log must not add another row to the result being paged. Read-access attempts remain durably archived.
    before = filters.before or datetime.now(UTC)
    query = query.where(
        or_(business_scope, entity_scope, own_security),
        AuditEvent.created_at <= before,
        AuditEvent.action.not_in(
            [
                "audit.search.success",
                "audit.search.failure",
                "requisition.history_view.success",
                "requisition.history_view.failure",
            ]
        ),
    )
    if filters.search:
        query = query.where(
            or_(
                AuditEvent.action.icontains(filters.search, autoescape=True),
                Requisition.reference.icontains(filters.search, autoescape=True),
            )
        )
    if filters.action:
        query = query.where(AuditEvent.action == filters.action)
    if filters.actor:
        query = query.where(Identity.display_name.icontains(filters.actor, autoescape=True))
    if filters.company:
        query = query.where(Entity.name.icontains(filters.company, autoescape=True))
    if filters.outcome:
        query = query.where(AuditEvent.details["outcome"].astext == filters.outcome)
    lower, upper = filters.bounds()
    if lower:
        query = query.where(AuditEvent.created_at >= lower)
    if upper:
        query = query.where(AuditEvent.created_at < upper)
    count = await s.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await s.execute(
            query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(filters.limit)
            .offset(filters.offset)
        )
    ).all()
    items = []
    for event, name, company, req_id, reference, attachment_id, filename, detached in rows:
        # The safe public envelope never returns raw audit JSON, signature strokes or Board identifiers.
        revision_id = event.details.get("revision_id")
        digest = event.details.get("content_digest")
        items.append(
            AuditRow(
                id=event.id,
                action=event.action,
                at=event.created_at,
                actor_id=event.actor_id,
                actor_name=name or "System",
                company=company,
                outcome=str(event.details.get("outcome", "success")),
                request_id=req_id,
                reference=reference,
                attachment_id=attachment_id if not detached else None,
                attachment_filename=filename,
                revision_id=UUID(str(revision_id)) if revision_id else None,
                content_digest=str(digest)
                if digest and event.details.get("resource_type") != "board"
                else None,
            )
        )
    return AuditPage(
        items=items, total=count or 0, limit=filters.limit, offset=filters.offset, before=before
    )
