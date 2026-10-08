import asyncio
import hashlib
from typing import Literal
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.access.service import get_scoped_request, require_action, require_attachment
from app.audit.service import record_event
from app.core.database import get_session
from app.core.errors import DomainError
from app.evidence.models import Attachment
from app.evidence.storage import Storage
from app.evidence.validation import validate
from app.identity.service import Actor, current_actor

router = APIRouter(prefix="/api/v1", tags=["Private documents"])


class AttachmentView(BaseModel):
    id: UUID
    filename: str
    media_type: str
    byte_size: int
    digest: str
    frozen: bool
    validation_state: str
    malware_scan: Literal["not_performed"] = "not_performed"


def view(file: Attachment) -> AttachmentView:
    return AttachmentView.model_validate(
        {
            name: getattr(file, name)
            for name in AttachmentView.model_fields
            if name != "malware_scan"
        }
    )


class AttachmentPage(BaseModel):
    items: list[AttachmentView]
    request_version: int
    uploads_enabled: bool
    max_bytes: int
    max_count: int


@router.get("/requisitions/{request_id}/attachments", response_model=AttachmentPage)
async def listing(
    request_id: UUID,
    request: Request,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> AttachmentPage:
    req = await get_scoped_request(s, request_id, actor)
    files = (
        await s.scalars(
            select(Attachment)
            .where(
                Attachment.requisition_id == req.id,
                Attachment.kind == "request_support",
                Attachment.detached.is_(False),
            )
            .order_by(Attachment.created_at, Attachment.id)
        )
    ).all()
    cfg = request.app.state.settings
    return AttachmentPage(
        items=[view(f) for f in files],
        request_version=req.version,
        uploads_enabled=request.app.state.uploads_enabled,
        max_bytes=cfg.attachment_max_bytes,
        max_count=cfg.attachment_max_count,
    )


@router.post(
    "/requisitions/{request_id}/attachments", response_model=AttachmentView, status_code=201
)
async def upload(
    request_id: UUID,
    request: Request,
    filename: str = Query(max_length=180),
    expected_version: int = Query(ge=1),
    upload_key: UUID = Query(),
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> AttachmentView:
    await s.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"upload:{upload_key}"},
    )
    req = await get_scoped_request(s, request_id, actor)
    await require_action(s, req, actor, "attachment_upload")
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
    existing = await s.scalar(select(Attachment).where(Attachment.upload_key == upload_key))
    if existing:
        if (
            existing.requisition_id != req.id
            or existing.uploaded_by != actor.id
            or existing.digest != digest
            or existing.filename != name
            or existing.detached
        ):
            raise DomainError(
                "IDEMPOTENCY_CONFLICT", "This upload key was used for different content."
            )
        return view(existing)
    if req.version != expected_version:
        raise DomainError("REVISION_CONFLICT", "The request changed. Reload before uploading.")
    count = await s.scalar(
        select(func.count())
        .select_from(Attachment)
        .where(Attachment.requisition_id == req.id, Attachment.detached.is_(False))
    )
    if (count or 0) >= request.app.state.settings.attachment_max_count:
        raise DomainError("VALIDATION_FAILED", "The request has reached its attachment limit.", 422)
    file_id = uuid4()
    key = f"requisitions/{req.id}/{file_id}/{digest}"
    storage: Storage = request.app.state.evidence_storage
    object_version = await storage.put(key, bytes(data), media)
    file = Attachment(
        id=file_id,
        requisition_id=req.id,
        uploaded_by=actor.id,
        upload_key=upload_key,
        kind="request_support",
        filename=name,
        media_type=media,
        byte_size=len(data),
        digest=digest,
        storage_key=key,
        object_version=object_version,
        validation_state="validated",
    )
    s.add(file)
    req.version += 1
    await s.flush()
    await record_event(
        s,
        action="evidence.uploaded",
        actor_id=actor.id,
        resource_id=file.id,
        entity_id=req.entity_id,
    )
    return view(file)


@router.delete("/attachments/{attachment_id}", status_code=204)
async def detach(
    attachment_id: UUID,
    expected_version: int = Query(ge=1),
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> Response:
    file = await require_attachment(s, attachment_id, actor)
    req = await get_scoped_request(s, file.requisition_id, actor)
    await require_action(s, req, actor, "attachment_upload")
    if file.frozen or file.kind != "request_support":
        raise DomainError("INVALID_STATE_TRANSITION", "Submitted evidence cannot be removed.")
    if req.version != expected_version:
        raise DomainError(
            "REVISION_CONFLICT", "The request changed. Reload before removing a document."
        )
    file.detached = True
    req.version += 1
    await record_event(
        s,
        action="evidence.detached",
        actor_id=actor.id,
        resource_id=file.id,
        entity_id=req.entity_id,
    )
    return Response(status_code=204)


@router.get("/attachments/{attachment_id}/content")
async def download(
    attachment_id: UUID,
    request: Request,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> Response:
    file = await require_attachment(s, attachment_id, actor)
    if file.validation_state != "validated":
        raise DomainError("RESOURCE_NOT_AVAILABLE", "The document is not available.", 404)
    storage: Storage = request.app.state.evidence_storage
    data = await storage.get(file.storage_key, file.digest, file.byte_size)
    return Response(
        data,
        media_type=file.media_type,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(file.filename, safe=""),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )
