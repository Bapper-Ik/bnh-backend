from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.service import get_scoped_request as get_request
from app.access.service import project_content, request_scope, require_action
from app.audit.models import OutboxItem
from app.audit.service import AuditDetails, record_event
from app.core.database import Identity, get_session
from app.core.errors import DomainError
from app.evidence.models import Attachment
from app.evidence.storage import Storage
from app.identity.service import Actor, current_actor
from app.organisation.models import Department, Entity
from app.organisation.service import membership
from app.requisitions.models import CommandResult, Decision, Requisition, Revision, SigningChallenge
from app.requisitions.schemas import (
    ChallengeView,
    CreateRequest,
    Intent,
    RequestView,
    SignedAction,
    StartRevision,
    UpdateRequest,
)
from app.requisitions.service import (
    DECLARATION,
    authorise_intent,
    content_digest,
    present,
    revision_view,
    select_vendor,
    total_for,
)

router = APIRouter(prefix="/api/v1/requisitions", tags=["Requisitions"])
approvals_router = APIRouter(prefix="/api/v1/approvals", tags=["Approvals"])


class Summary(BaseModel):
    id: UUID
    reference: str
    state: str
    total: str
    description: str
    created_at: str
    requester_name: str
    required_authority: str | None


class Page(BaseModel):
    items: list[Summary]
    total: int
    limit: int
    offset: int


async def key_lock(s: AsyncSession, actor: Actor, key: UUID) -> None:
    await s.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"{actor.id}:{key}"},
    )


@router.get("", response_model=Page)
async def list_requests(
    inbox: bool = False,
    search: str = Query(default="", max_length=250),
    state: str = Query(default="", max_length=40),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> Page:
    condition = request_scope(actor, inbox=inbox)
    query = (
        select(Requisition, Revision, Identity)
        .outerjoin(Revision, Revision.id == Requisition.current_revision_id)
        .join(Identity, Identity.id == Requisition.requester_id)
        .where(condition)
    )
    if inbox:
        query = query.where(
            Requisition.state.in_(
                ["PENDING_AUTHORITY", "AWAITING_BOARD_RESOLUTION", "AWAITING_CHAIRMAN_SIGNOFF"]
            )
        )
    if search:
        query = query.where(
            Requisition.reference.icontains(search, autoescape=True)
            | Requisition.content["description"].astext.icontains(search, autoescape=True)
        )
    if state:
        query = query.where(Requisition.state == state)
    count = await s.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await s.execute(
            query.order_by(Requisition.created_at.desc(), Requisition.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return Page(
        items=[
            Summary(
                id=r.id,
                reference=r.reference,
                state=r.state,
                total=format(r.total, ".2f"),
                description=str(r.content.get("description", "")),
                created_at=r.created_at.isoformat(),
                requester_name=rev.requester_name if rev else i.display_name,
                required_authority=rev.authority if rev else None,
            )
            for r, rev, i in rows
        ],
        total=count or 0,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=RequestView, status_code=201)
async def create(
    body: CreateRequest,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> RequestView:
    if actor.account.read_only:
        raise DomainError("ACCESS_DENIED", "Read-only reviewers cannot create requisitions.", 403)
    await key_lock(s, actor, body.creation_key)
    digest = content_digest(body.model_dump(mode="json"))
    existing = await s.scalar(
        select(Requisition).where(
            Requisition.requester_id == actor.id, Requisition.creation_key == body.creation_key
        )
    )
    if existing:
        if existing.creation_digest != digest:
            raise DomainError(
                "IDEMPOTENCY_CONFLICT", "This creation key was used for different content."
            )
        return await present(s, existing, actor)
    member = await membership(s, actor.id, body.entity_id)
    context = await select_vendor(s, actor, body.entity_id, body)
    serial = await s.scalar(text("SELECT nextval('custodian.request_reference')"))
    req = Requisition(
        id=uuid4(),
        reference=f"BNH-{datetime.now(UTC).year}-{serial:06d}",
        requester_id=actor.id,
        entity_id=body.entity_id,
        department_id=member.department_id,
        creation_key=body.creation_key,
        creation_digest=digest,
        context=context,
        content=body.content.model_dump(mode="json"),
        total=Decimal(total_for(body.content)),
    )
    s.add(req)
    await s.flush()
    await record_event(
        s,
        action="requisition.created",
        actor_id=actor.id,
        resource_id=req.id,
        entity_id=req.entity_id,
    )
    return await present(s, req, actor)


@router.get("/{request_id}", response_model=RequestView)
async def detail(
    request_id: UUID,
    revision: int | None = Query(default=None, ge=1),
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> RequestView:
    req = await get_request(s, request_id, actor)
    return (
        await revision_view(s, req, actor, revision) if revision else await present(s, req, actor)
    )


@router.post("/{request_id}/revisions", response_model=RequestView)
async def start_revision(
    request_id: UUID,
    body: StartRevision,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> RequestView:
    await key_lock(s, actor, body.idempotency_key)
    req = await get_request(s, request_id, actor)
    payload = content_digest(
        {
            "operation": "start_revision",
            "request_id": str(req.id),
            "command": body.model_dump(mode="json"),
        }
    )
    cached = await s.scalar(
        select(CommandResult).where(
            CommandResult.actor_id == actor.id,
            CommandResult.idempotency_key == body.idempotency_key,
        )
    )
    if cached:
        if cached.payload_digest != payload:
            raise DomainError("IDEMPOTENCY_CONFLICT", "This key was used for a different action.")
        result = RequestView.model_validate(cached.result)
        content, redacted = project_content(result.content.model_dump(mode="json"), actor)
        return result.model_copy(
            update={
                "content": result.content.model_validate(content),
                "redacted_fields": sorted(set(result.redacted_fields + redacted)),
                "available_actions": [],
            }
        )
    await require_action(s, req, actor, "revise")
    if req.version != body.expected_version:
        raise DomainError(
            "REVISION_CONFLICT", "This request changed. Reload before starting a correction."
        )
    req.state = "DRAFT"
    req.version += 1
    await record_event(
        s,
        action="requisition.revision_created",
        actor_id=actor.id,
        resource_id=req.id,
        entity_id=req.entity_id,
        details=AuditDetails(revision_id=req.current_revision_id),
    )
    result = await present(s, req, actor)
    s.add(
        CommandResult(
            actor_id=actor.id,
            idempotency_key=body.idempotency_key,
            payload_digest=payload,
            resource_id=req.id,
            result=result.model_dump(mode="json"),
        )
    )
    return result


@router.put("/{request_id}/draft", response_model=RequestView)
async def update(
    request_id: UUID,
    body: UpdateRequest,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> RequestView:
    req = await get_request(s, request_id, actor)
    await require_action(s, req, actor, "edit")
    if req.requester_id != actor.id or req.state != "DRAFT":
        raise DomainError(
            "INVALID_STATE_TRANSITION", "Start a correction before editing a returned request."
        )
    if req.version != body.expected_version:
        raise DomainError("REVISION_CONFLICT", "A newer version exists. Reload before editing.")
    if body.vendor_selection:
        req.context = await select_vendor(s, actor, req.entity_id, body)
    elif body.content.vendor.model_dump(mode="json") != req.content.get("vendor"):
        req.context = {}
    req.content, req.total = body.content.model_dump(mode="json"), Decimal(total_for(body.content))
    req.version += 1
    await record_event(
        s,
        action="requisition.updated",
        actor_id=actor.id,
        resource_id=req.id,
        entity_id=req.entity_id,
    )
    return await present(s, req, actor)


@router.post("/{request_id}/signing-challenges", response_model=ChallengeView, status_code=201)
async def challenge(
    request_id: UUID,
    body: Intent,
    request: Request,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> ChallengeView:
    req = await get_request(s, request_id, actor)
    if body.action != "submit" and not getattr(
        request.app.state, "individual_decisions_enabled", False
    ):
        raise DomainError(
            "ACCESS_DENIED", "Individual approval actions are not available in this release.", 403
        )
    try:
        bound = await authorise_intent(s, req, actor, body)
    except ValueError as exc:
        raise DomainError("VALIDATION_FAILED", str(exc), 422) from exc
    if datetime.now(UTC) - actor.login_session.authenticated_at > timedelta(
        minutes=request.app.state.settings.signing_minutes
    ):
        raise DomainError(
            "FRESH_AUTHENTICATION_REQUIRED", "Confirm your password before signing.", 401
        )
    expires = datetime.now(UTC) + timedelta(minutes=request.app.state.settings.signing_minutes)
    signing = SigningChallenge(
        id=uuid4(),
        requisition_id=req.id,
        actor_id=actor.id,
        action=body.action,
        expected_version=body.expected_version,
        content_digest=content_digest(bound),
        expires_at=expires,
    )
    s.add(signing)
    await record_event(
        s,
        action="signature.challenged",
        actor_id=actor.id,
        resource_id=req.id,
        entity_id=req.entity_id,
    )
    route = bound["route"]
    assert isinstance(route, dict)
    return ChallengeView(
        id=signing.id,
        content_digest=signing.content_digest,
        expires_at=expires.isoformat(),
        total=format(req.total, ".2f"),
        authority=str(route["authority"]) if body.action == "submit" else None,
        routing_explanation=str(route["explanation"]) if body.action == "submit" else None,
        statement=DECLARATION
        if body.action == "submit"
        else f"I have reviewed this exact requisition and confirm my decision to {body.action}.",
    )


@router.post("/{request_id}/actions", response_model=RequestView)
async def act(
    request_id: UUID,
    body: SignedAction,
    request: Request,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> RequestView:
    await key_lock(s, actor, body.idempotency_key)
    req = await get_request(s, request_id, actor)
    payload_hash = content_digest(
        {"request_id": str(req.id), "command": body.model_dump(mode="json")}
    )
    cached = await s.scalar(
        select(CommandResult).where(
            CommandResult.actor_id == actor.id,
            CommandResult.idempotency_key == body.idempotency_key,
        )
    )
    if cached:
        if cached.payload_digest != payload_hash:
            raise DomainError("IDEMPOTENCY_CONFLICT", "This key was used for a different action.")
        result = RequestView.model_validate(cached.result)
        content, redacted = project_content(result.content.model_dump(mode="json"), actor)
        return result.model_copy(
            update={
                "content": result.content.model_validate(content),
                "redacted_fields": sorted(set(result.redacted_fields + redacted)),
                "available_actions": [],
            }
        )
    if body.action != "submit" and not getattr(
        request.app.state, "individual_decisions_enabled", False
    ):
        raise DomainError(
            "ACCESS_DENIED", "Individual approval actions are not available in this release.", 403
        )
    try:
        bound = await authorise_intent(s, req, actor, body)
    except ValueError as exc:
        raise DomainError("VALIDATION_FAILED", str(exc), 422) from exc
    signing = await s.scalar(
        select(SigningChallenge).where(SigningChallenge.id == body.challenge_id).with_for_update()
    )
    now = datetime.now(UTC)
    if (
        not signing
        or signing.actor_id != actor.id
        or signing.requisition_id != req.id
        or signing.consumed
        or signing.expires_at <= now
        or signing.action != body.action
        or signing.expected_version != req.version
        or signing.content_digest != content_digest(bound)
        or now - actor.login_session.authenticated_at
        > timedelta(minutes=request.app.state.settings.signing_minutes)
    ):
        raise DomainError(
            "SIGNATURE_INVALID",
            "The signature challenge expired or its content changed. Review and sign again.",
        )
    if body.signer_name.strip().casefold() != actor.identity.display_name.strip().casefold():
        raise DomainError(
            "SIGNATURE_INVALID", "Enter your full name as shown in your profile.", 422
        )
    signature = {
        "actor_id": str(actor.id),
        "name": body.signer_name.strip(),
        "at": now.isoformat(),
        "intent": body.action,
        "consent": True,
        "challenge_id": str(signing.id),
        "content_digest": signing.content_digest,
        "authenticated_at": actor.login_session.authenticated_at.isoformat(),
        "declaration": bound["declaration"],
        "declaration_version": bound["declaration_version"],
        "strokes": [[p.model_dump() for p in stroke] for stroke in body.strokes],
    }
    signing.consumed = True
    if body.action == "submit":
        route = bound["route"]
        assert isinstance(route, dict)
        entity, department = (
            await s.get(Entity, req.entity_id),
            await s.get(Department, req.department_id),
        )
        assert entity and department
        files = (
            await s.scalars(
                select(Attachment).where(
                    Attachment.requisition_id == req.id,
                    Attachment.kind == "request_support",
                    Attachment.detached.is_(False),
                    Attachment.id.not_in([UUID(x) for x in req.excluded_attachment_ids]),
                )
            )
        ).all()
        storage: Storage = request.app.state.evidence_storage
        for file in files:
            await storage.get(file.storage_key, file.digest, file.byte_size)
            if not file.frozen:
                file.frozen = True
        # Provider reads may take time; eligibility and freshness must still hold now.
        checked_at = datetime.now(UTC)
        if (
            checked_at >= signing.expires_at
            or checked_at - actor.login_session.authenticated_at
            > timedelta(minutes=request.app.state.settings.signing_minutes)
        ):
            raise DomainError(
                "SIGNATURE_INVALID",
                "Signing expired while checking documents. Review and sign again.",
            )
        if content_digest(await authorise_intent(s, req, actor, body)) != signing.content_digest:
            raise DomainError(
                "SIGNATURE_INVALID", "The signing context changed. Review and sign again."
            )
        signature["at"] = checked_at.isoformat()
        req.revision_number += 1
        revision = Revision(
            id=uuid4(),
            requisition_id=req.id,
            number=req.revision_number,
            context=bound,
            content=req.content,
            total=req.total,
            requester_name=actor.identity.display_name,
            department_name=department.name,
            entity_name=entity.name,
            authority=str(route["authority"]),
            approver_id=UUID(str(route["approver_id"])) if route["approver_id"] else None,
            policy_version=str(route["policy_version"]),
            routing_explanation=str(route["explanation"]),
            content_digest=signing.content_digest,
            signature=signature,
        )
        s.add(revision)
        await s.flush()
        req.current_revision_id = revision.id
        req.state = (
            "AWAITING_BOARD_RESOLUTION" if revision.authority == "board" else "PENDING_AUTHORITY"
        )
        event = "requisition.resubmitted" if req.revision_number > 1 else "requisition.submitted"
    else:
        assert req.current_revision_id
        s.add(
            Decision(
                revision_id=req.current_revision_id,
                actor_id=actor.id,
                action=body.action,
                reason=body.reason,
                signature=signature,
                content_digest=signing.content_digest,
            )
        )
        req.state = {
            "approve": "APPROVED",
            "reject": "REJECTED",
            "return": "RETURNED_FOR_REVISION",
        }[body.action]
        event = {
            "approve": "requisition.approved",
            "reject": "requisition.rejected",
            "return": "requisition.returned",
        }[body.action]
    req.version += 1
    await s.flush()
    audit = await record_event(
        s,
        action=event,
        actor_id=actor.id,
        resource_id=req.id,
        entity_id=req.entity_id,
        details=AuditDetails(
            revision_id=req.current_revision_id,
            policy_version="bnh-doa-v1",
            content_digest=signing.content_digest,
        ),
        event_key=f"command:{actor.id}:{body.idempotency_key}",
    )
    await record_event(
        s,
        action="signature.captured",
        actor_id=actor.id,
        resource_id=req.id,
        entity_id=req.entity_id,
        details=AuditDetails(
            revision_id=req.current_revision_id, content_digest=signing.content_digest
        ),
    )
    if body.action == "submit":
        await record_event(
            s,
            action="requisition.routed",
            actor_id=actor.id,
            resource_id=req.id,
            entity_id=req.entity_id,
            details=AuditDetails(
                revision_id=req.current_revision_id,
                policy_version="bnh-doa-v1",
                content_digest=signing.content_digest,
            ),
        )
    s.add(OutboxItem(event_id=audit.id, destination="requisition_notification"))
    result = await present(s, req, actor)
    s.add(
        CommandResult(
            actor_id=actor.id,
            idempotency_key=body.idempotency_key,
            payload_digest=payload_hash,
            resource_id=req.id,
            result=result.model_dump(mode="json"),
        )
    )
    await s.flush()
    return result


@approvals_router.get("/inbox", response_model=Page)
async def approval_inbox(
    search: str = Query(default="", max_length=250),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> Page:
    return await list_requests(
        inbox=True,
        search=search,
        state="PENDING_AUTHORITY",
        limit=limit,
        offset=offset,
        actor=actor,
        s=s,
    )
