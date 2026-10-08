import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.access.service import get_scoped_request
from app.audit.models import OutboxItem
from app.audit.service import AuditDetails, record_event
from app.board.models import ChairmanDecision, Resolution
from app.board.schemas import BoardCase, BoardIntent, BoardSignedAction, SaveResolution
from app.board.service import (
    HOLDS,
    OUTCOMES,
    STATEMENTS,
    available,
    board_access,
    bound_intent,
    case_view,
    editable,
    records,
    version,
)
from app.core.database import get_session
from app.core.errors import DomainError
from app.evidence.models import Attachment
from app.evidence.storage import Storage
from app.evidence.validation import validate
from app.identity.service import Actor, current_actor
from app.requisitions.models import CommandResult, Requisition, SigningChallenge
from app.requisitions.router import key_lock
from app.requisitions.schemas import ChallengeView, RequestView
from app.requisitions.service import content_digest, present

router = APIRouter(prefix="/api/v1", tags=["Board resolutions"])


async def event(
    s: AsyncSession, req: Requisition, actor: Actor, action: str, record: Resolution
) -> None:
    await record_event(
        s,
        action=action,
        actor_id=actor.id,
        resource_id=req.id,
        entity_id=req.entity_id,
        details=AuditDetails(revision_id=req.current_revision_id, resolution_id=record.id),
    )


@router.get("/requisitions/{request_id}/board", response_model=BoardCase)
async def board_case(
    request_id: UUID,
    request: Request,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> BoardCase:
    req = await get_scoped_request(s, request_id, actor)
    return await case_view(s, req, actor, request.app.state.uploads_enabled)


async def cached(s: AsyncSession, actor: Actor, key: UUID, digest: str) -> CommandResult | None:
    result = await s.scalar(
        select(CommandResult).where(
            CommandResult.actor_id == actor.id, CommandResult.idempotency_key == key
        )
    )
    if result and result.payload_digest != digest:
        raise DomainError("IDEMPOTENCY_CONFLICT", "This key was used for different content.")
    return result


@router.post("/requisitions/{request_id}/board-resolutions", response_model=BoardCase)
async def save(
    request_id: UUID,
    body: SaveResolution,
    request: Request,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> BoardCase:
    await key_lock(s, actor, body.idempotency_key)
    req = await get_scoped_request(s, request_id, actor)
    rev, role, _ = await board_access(s, req, actor)
    digest = content_digest(
        {"operation": "board_save", "request": str(req.id), "body": body.model_dump(mode="json")}
    )
    if await cached(s, actor, body.idempotency_key, digest):
        return await case_view(s, req, actor, request.app.state.uploads_enabled)
    rows = await records(s, req)
    actions = await available(s, req, role, rows)
    version(req, body.expected_version)
    if "edit" in actions:
        record = rows[-1]
        record.data = body.data.model_dump(mode="json")
        action = "board.draft_updated"
    elif set(actions).intersection({"create", "correct", "later_resolution"}):
        predecessor = rows[-1] if rows else None
        kind = (
            "correction"
            if "correct" in actions
            else "later_resolution"
            if predecessor
            else "initial"
        )
        record = Resolution(
            id=uuid4(),
            revision_id=rev.id,
            number=len(rows) + 1,
            predecessor_id=predecessor.id if predecessor else None,
            kind=kind,
            recorded_by=actor.id,
            data=body.data.model_dump(mode="json"),
            signature={},
            evidence_id=predecessor.evidence_id if predecessor and kind == "correction" else None,
        )
        s.add(record)
        action = "board.draft_created"
    else:
        raise DomainError(
            "ACCESS_DENIED", "This Board case cannot be edited by you at this stage.", 403
        )
    req.version += 1
    await s.flush()
    await event(s, req, actor, action, record)
    s.add(
        CommandResult(
            actor_id=actor.id,
            idempotency_key=body.idempotency_key,
            payload_digest=digest,
            resource_id=req.id,
            result={"resolution_id": str(record.id)},
        )
    )
    return await case_view(s, req, actor, request.app.state.uploads_enabled)


async def resolution_request(
    s: AsyncSession, resolution_id: UUID, actor: Actor
) -> tuple[Resolution, Requisition]:
    # Read only an identifier before applying request and Board scope. Requisition lock serialises every mutation.
    from app.requisitions.models import Revision

    row = await s.get(Resolution, resolution_id)
    rev = await s.get(Revision, row.revision_id) if row else None
    if not row or not rev:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Board record not found.", 404)
    req = await get_scoped_request(s, rev.requisition_id, actor)
    await board_access(s, req, actor)
    await s.refresh(row)
    return row, req


@router.post("/board-resolutions/{resolution_id}/attachments", response_model=BoardCase)
async def upload(
    resolution_id: UUID,
    request: Request,
    filename: str = Query(max_length=180),
    expected_version: int = Query(ge=1),
    upload_key: UUID = Query(),
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> BoardCase:
    await key_lock(s, actor, upload_key)
    row, req = await resolution_request(s, resolution_id, actor)
    limit = request.app.state.settings.attachment_max_bytes
    data = bytearray()
    try:
        async with asyncio.timeout(30):
            async for chunk in request.stream():
                if len(data) + len(chunk) > limit:
                    raise DomainError(
                        "VALIDATION_FAILED", "The file exceeds the upload size limit.", 422
                    )
                data.extend(chunk)
    except TimeoutError as exc:
        raise DomainError(
            "VALIDATION_FAILED", "The upload timed out. Retry the file.", 422
        ) from exc
    name, media = await run_in_threadpool(
        validate, bytes(data), filename, request.headers.get("content-type", ""), limit
    )
    digest = hashlib.sha256(data).hexdigest()
    payload = content_digest(
        {"operation": "board_upload", "record": str(row.id), "digest": digest, "filename": name}
    )
    if await cached(s, actor, upload_key, payload):
        return await case_view(s, req, actor, request.app.state.uploads_enabled)
    await editable(s, req, actor, row.id, expected_version)
    storage: Storage = request.app.state.evidence_storage
    file_id = uuid4()
    key = f"board/{row.id}/{file_id}/{digest}"
    object_version = await storage.put(key, bytes(data), media)
    file = Attachment(
        id=file_id,
        requisition_id=req.id,
        uploaded_by=actor.id,
        kind="board_resolution",
        filename=name,
        media_type=media,
        byte_size=len(data),
        digest=digest,
        storage_key=key,
        object_version=object_version,
        validation_state="validated",
    )
    s.add(file)
    await s.flush()
    row.evidence_id = file.id
    req.version += 1
    await event(s, req, actor, "board.evidence_uploaded", row)
    s.add(
        CommandResult(
            actor_id=actor.id,
            idempotency_key=upload_key,
            payload_digest=payload,
            resource_id=req.id,
            result={"attachment_id": str(file.id)},
        )
    )
    return await case_view(s, req, actor, request.app.state.uploads_enabled)


def fresh(request: Request, actor: Actor) -> datetime:
    now = datetime.now(UTC)
    if now - actor.login_session.authenticated_at > timedelta(
        minutes=request.app.state.settings.signing_minutes
    ):
        raise DomainError(
            "FRESH_AUTHENTICATION_REQUIRED", "Confirm your password before signing.", 401
        )
    return now


@router.post(
    "/board-resolutions/{resolution_id}/signing-challenges",
    response_model=ChallengeView,
    status_code=201,
)
async def challenge(
    resolution_id: UUID,
    body: BoardIntent,
    request: Request,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> ChallengeView:
    row, req = await resolution_request(s, resolution_id, actor)
    _, _, bound = await bound_intent(s, req, actor, row.id, body)
    expires = fresh(request, actor) + timedelta(minutes=request.app.state.settings.signing_minutes)
    signing = SigningChallenge(
        id=uuid4(),
        requisition_id=req.id,
        actor_id=actor.id,
        action=body.action,
        expected_version=req.version,
        content_digest=content_digest(bound),
        expires_at=expires,
    )
    s.add(signing)
    await event(s, req, actor, "signature.challenged", row)
    return ChallengeView(
        id=signing.id,
        content_digest=signing.content_digest,
        expires_at=expires.isoformat(),
        statement=STATEMENTS[body.action],
        total=format(req.total, ".2f"),
        authority="board",
        routing_explanation=f"Resolution {row.number}: {row.data['outcome']}",
    )


@router.post("/board-resolutions/{resolution_id}/actions", response_model=RequestView)
async def act(
    resolution_id: UUID,
    body: BoardSignedAction,
    request: Request,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> RequestView:
    await key_lock(s, actor, body.idempotency_key)
    row, req = await resolution_request(s, resolution_id, actor)
    digest = content_digest(
        {"operation": "board_action", "record": str(row.id), "body": body.model_dump(mode="json")}
    )
    old = await cached(s, actor, body.idempotency_key, digest)
    if old:
        return RequestView.model_validate(old.result).model_copy(update={"available_actions": []})
    row, evidence, bound = await bound_intent(s, req, actor, row.id, body)
    signing = await s.scalar(
        select(SigningChallenge).where(SigningChallenge.id == body.challenge_id).with_for_update()
    )
    now = fresh(request, actor)
    if (
        not signing
        or signing.actor_id != actor.id
        or signing.requisition_id != req.id
        or signing.action != body.action
        or signing.expected_version != req.version
        or signing.consumed
        or signing.expires_at <= now
        or signing.content_digest != content_digest(bound)
    ):
        raise DomainError(
            "SIGNATURE_INVALID", "The challenge expired or changed. Review and sign again."
        )
    if body.signer_name.strip().casefold() != actor.identity.display_name.strip().casefold():
        raise DomainError(
            "SIGNATURE_INVALID", "Enter your full name as shown in your profile.", 422
        )
    storage: Storage = request.app.state.evidence_storage
    await storage.get(evidence.storage_key, evidence.digest, evidence.byte_size)
    now = fresh(request, actor)
    _, _, checked = await bound_intent(s, req, actor, row.id, body)
    if now >= signing.expires_at or content_digest(checked) != signing.content_digest:
        raise DomainError(
            "SIGNATURE_INVALID", "The signing context changed. Review and sign again."
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
        "declaration_version": "board-v1",
        "strokes": [[p.model_dump() for p in stroke] for stroke in body.strokes],
    }
    signing.consumed = True
    if body.action == "board_submit":
        row.recorded_by = actor.id
        row.signature = signature
        if not evidence.frozen:
            evidence.frozen = True
        if req.state not in HOLDS:
            req.state = "AWAITING_CHAIRMAN_SIGNOFF"
        action = "board.recorded"
    else:
        s.add(
            ChairmanDecision(
                resolution_id=row.id,
                actor_id=actor.id,
                action=body.action,
                reason=body.reason,
                outcome=str(row.data["outcome"]),
                signature=signature,
            )
        )
        if body.action == "board_confirm":
            req.state = OUTCOMES[str(row.data["outcome"])]
            action = "board.confirmed"
        else:
            if req.state not in HOLDS:
                req.state = "AWAITING_BOARD_RESOLUTION"
            action = "board.returned"
    req.version += 1
    await s.flush()
    audit = await record_event(
        s,
        action=action,
        actor_id=actor.id,
        resource_id=req.id,
        entity_id=req.entity_id,
        details=AuditDetails(
            revision_id=req.current_revision_id,
            resolution_id=row.id,
            content_digest=signing.content_digest,
        ),
        event_key=f"command:{actor.id}:{body.idempotency_key}",
    )
    await event(s, req, actor, "signature.captured", row)
    s.add(OutboxItem(event_id=audit.id, destination="requisition_notification"))
    result = await present(s, req, actor)
    s.add(
        CommandResult(
            actor_id=actor.id,
            idempotency_key=body.idempotency_key,
            payload_digest=digest,
            resource_id=req.id,
            result=result.model_dump(mode="json"),
        )
    )
    return result
