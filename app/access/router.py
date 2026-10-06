from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import ReviewGrant
from app.access.service import (
    get_scoped_request,
    request_scope,
    require_action,
    require_attachment,
)
from app.audit.service import AuditDetails, record_event
from app.core.database import get_session
from app.core.errors import DomainError
from app.identity.models import Account
from app.identity.schemas import Command
from app.identity.service import Actor, current_actor, require_permission
from app.organisation.models import Entity, Office
from app.requisitions.models import Requisition, Revision

router = APIRouter(prefix="/api/v1/access", tags=["Record access"])


class CapabilityView(BaseModel):
    requisition_id: UUID
    actions: list[str]
    read_only: bool


class CapabilityPage(BaseModel):
    items: list[CapabilityView]
    total: int
    limit: int
    offset: int


class AttachmentAccess(BaseModel):
    id: UUID
    requisition_id: UUID
    filename: str
    media_type: str
    validation_state: str


class ReviewInput(Command):
    identity_id: UUID
    entity_id: UUID
    active: bool = True


async def capabilities(session: AsyncSession, req: Requisition, actor: Actor) -> CapabilityView:
    actions = []
    for action in (
        "read",
        "edit",
        "submit",
        "approve",
        "reject",
        "return",
        "board_record",
        "attachment_upload",
        "export",
    ):
        try:
            await require_action(session, req, actor, action)
            actions.append(action)
        except DomainError:
            pass
    return CapabilityView(requisition_id=req.id, actions=actions, read_only=actor.account.read_only)


@router.get("/requisitions", response_model=CapabilityPage)
async def scoped_list(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> CapabilityPage:
    query = (
        select(Requisition)
        .outerjoin(Revision, Revision.id == Requisition.current_revision_id)
        .where(request_scope(actor))
    )
    count = await s.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await s.scalars(
            query.order_by(Requisition.created_at, Requisition.id).offset(offset).limit(limit)
        )
    ).all()
    return CapabilityPage(
        items=[await capabilities(s, req, actor) for req in rows],
        total=count or 0,
        limit=limit,
        offset=offset,
    )


@router.get("/requisitions/{request_id}", response_model=CapabilityView)
async def scoped_detail(
    request_id: UUID,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> CapabilityView:
    return await capabilities(s, await get_scoped_request(s, request_id, actor), actor)


@router.get("/attachments/{attachment_id}", response_model=AttachmentAccess)
async def attachment_access(
    attachment_id: UUID,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> AttachmentAccess:
    attachment = await require_attachment(s, attachment_id, actor)
    return AttachmentAccess(
        id=attachment.id,
        requisition_id=attachment.requisition_id,
        filename=attachment.filename,
        media_type=attachment.media_type,
        validation_state=attachment.validation_state,
    )


@router.post("/review-grants", response_model=ReviewInput)
async def review_grant(
    body: ReviewInput,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> ReviewInput:
    require_permission(actor, "office_assignment:manage")
    if body.identity_id == actor.id:
        raise DomainError("ACCESS_DENIED", "Operators cannot grant themselves review access.", 403)
    account = await s.scalar(
        select(Account).where(Account.identity_id == body.identity_id).with_for_update()
    )
    entity = await s.get(Entity, body.entity_id)
    if not account or not account.active or not entity or not entity.active:
        raise DomainError("VALIDATION_FAILED", "Select an active account and company.", 422)
    if body.active and await s.scalar(
        select(Office.id).where(Office.identity_id == body.identity_id, Office.active.is_(True))
    ):
        raise DomainError(
            "AUTHORITY_ASSIGNMENT_BLOCKED",
            "Revoke financial appointments before making an account read-only.",
        )
    grant = await s.scalar(
        select(ReviewGrant)
        .where(ReviewGrant.identity_id == body.identity_id, ReviewGrant.entity_id == body.entity_id)
        .with_for_update()
    )
    if grant and grant.active == body.active and (not body.active or account.read_only):
        return body
    if grant:
        grant.active = body.active
    else:
        s.add(ReviewGrant(**body.model_dump()))
    if body.active:
        account.read_only = True
    await record_event(
        s,
        action="access.permission_change.success",
        actor_id=actor.id,
        resource_id=body.identity_id,
        entity_id=body.entity_id,
        details=AuditDetails(changed_fields=["account_state"]),
    )
    return body
