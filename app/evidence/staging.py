"""Short-lived, owner-scoped uploads before a requisition exists."""

import asyncio
import hashlib
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.concurrency import run_in_threadpool

from app.audit.service import record_event
from app.core.database import get_session
from app.core.errors import DomainError
from app.evidence.models import Attachment, StagedUpload
from app.evidence.router import AttachmentPage, AttachmentView
from app.evidence.storage import Storage
from app.evidence.validation import validate
from app.identity.service import Actor, current_actor
from app.organisation.service import membership
from app.requisitions.models import Requisition

router = APIRouter(prefix="/api/v1/staged-attachments", tags=["Private documents"])


async def scope(s: AsyncSession, actor: Actor, entity_id: UUID) -> None:
    if actor.account.read_only:
        raise DomainError("ACCESS_DENIED", "Read-only accounts cannot upload documents.", 403)
    await membership(s, actor.id, entity_id)


def preview(file: StagedUpload) -> AttachmentView:
    return AttachmentView(
        id=file.id,
        filename=file.filename,
        media_type=file.media_type,
        byte_size=len(file.data),
        digest=file.digest,
        frozen=False,
        validation_state="validated",
    )


async def cleanup(s: AsyncSession, owner: UUID | None = None) -> None:
    query = delete(StagedUpload).where(StagedUpload.expires_at <= datetime.now(UTC))
    if owner:
        query = query.where(StagedUpload.uploaded_by == owner)
    await s.execute(query)


async def cleanup_loop(sessions: async_sessionmaker[AsyncSession]) -> None:
    while True:
        try:
            async with sessions() as s, s.begin():
                await cleanup(s)
        except SQLAlchemyError:
            logging.getLogger(__name__).warning("Temporary upload cleanup will retry.")
        await asyncio.sleep(3600)


@router.get("", response_model=AttachmentPage)
async def listing(
    request: Request,
    entity_id: UUID,
    creation_key: UUID,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> AttachmentPage:
    await scope(s, actor, entity_id)
    files = (
        await s.scalars(
            select(StagedUpload)
            .where(
                StagedUpload.uploaded_by == actor.id,
                StagedUpload.entity_id == entity_id,
                StagedUpload.creation_key == creation_key,
                StagedUpload.expires_at > datetime.now(UTC),
            )
            .order_by(StagedUpload.created_at, StagedUpload.id)
        )
    ).all()
    cfg = request.app.state.settings
    return AttachmentPage(
        items=[preview(f) for f in files],
        request_version=0,
        uploads_enabled=request.app.state.uploads_enabled,
        max_bytes=cfg.attachment_max_bytes,
        max_count=cfg.attachment_max_count,
    )


@router.post("", response_model=AttachmentView, status_code=201)
async def upload(
    request: Request,
    entity_id: UUID,
    creation_key: UUID,
    upload_key: UUID,
    filename: str = Query(max_length=180),
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> AttachmentView:
    await scope(s, actor, entity_id)
    # Same lock as requisition creation: a late upload must never miss the claim.
    await s.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"{actor.id}:{creation_key}"},
    )
    if await s.scalar(
        select(Requisition.id).where(
            Requisition.requester_id == actor.id, Requisition.creation_key == creation_key
        )
    ):
        raise DomainError("REVISION_CONFLICT", "This draft was saved. Reopen it to add documents.")
    if not request.app.state.uploads_enabled:
        raise DomainError("SERVICE_UNAVAILABLE", "Private document storage is unavailable.", 503)
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
    await cleanup(s, actor.id)
    if await s.scalar(select(Attachment.id).where(Attachment.upload_key == upload_key)):
        raise DomainError(
            "IDEMPOTENCY_CONFLICT", "This upload key has already been attached to a saved request."
        )
    existing = await s.get(StagedUpload, upload_key)
    if existing:
        if (
            existing.uploaded_by != actor.id
            or existing.entity_id != entity_id
            or existing.creation_key != creation_key
            or existing.digest != digest
            or existing.filename != name
        ):
            raise DomainError(
                "IDEMPOTENCY_CONFLICT", "This upload key was used for different content."
            )
        return preview(existing)
    # The authenticated account row serialises uploads across this person's forms.
    count = await s.scalar(
        select(func.count()).select_from(StagedUpload).where(StagedUpload.uploaded_by == actor.id)
    )
    if (count or 0) >= request.app.state.settings.attachment_max_count:
        raise DomainError(
            "VALIDATION_FAILED", "Save or remove your pending documents before uploading more.", 422
        )
    file = StagedUpload(
        id=upload_key,
        uploaded_by=actor.id,
        entity_id=entity_id,
        creation_key=creation_key,
        filename=name,
        media_type=media,
        digest=digest,
        data=bytes(data),
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    s.add(file)
    await s.flush()
    await record_event(
        s, action="evidence.staged", actor_id=actor.id, resource_id=file.id, entity_id=entity_id
    )
    return preview(file)


async def owned(s: AsyncSession, actor: Actor, file_id: UUID) -> StagedUpload:
    file = await s.scalar(
        select(StagedUpload)
        .where(
            StagedUpload.id == file_id,
            StagedUpload.uploaded_by == actor.id,
            StagedUpload.expires_at > datetime.now(UTC),
        )
        .with_for_update()
    )
    if not file:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Document not found.", 404)
    await scope(s, actor, file.entity_id)
    return file


@router.get("/{file_id}/content")
async def download(
    file_id: UUID,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> Response:
    from urllib.parse import quote

    file = await owned(s, actor, file_id)
    return Response(
        file.data,
        media_type=file.media_type,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(file.filename, safe=""),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


@router.delete("/{file_id}", status_code=204)
async def remove(
    file_id: UUID,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> Response:
    file = await owned(s, actor, file_id)
    await record_event(
        s,
        action="evidence.staged_removed",
        actor_id=actor.id,
        resource_id=file.id,
        entity_id=file.entity_id,
    )
    await s.delete(file)
    return Response(status_code=204)


async def claim(
    s: AsyncSession, req: Requisition, storage: Storage, expected_ids: list[UUID]
) -> None:
    files = (
        await s.scalars(
            select(StagedUpload)
            .where(
                StagedUpload.uploaded_by == req.requester_id,
                StagedUpload.creation_key == req.creation_key,
            )
            .order_by(StagedUpload.id)
            .with_for_update()
        )
    ).all()
    if len(expected_ids) != len(set(expected_ids)) or {f.id for f in files} != set(expected_ids):
        raise DomainError(
            "DOCUMENTS_CHANGED",
            "Supporting documents changed or expired. Reload documents before saving.",
        )
    for staged in files:
        if await s.scalar(select(Attachment.id).where(Attachment.upload_key == staged.id)):
            raise DomainError(
                "DOCUMENTS_CHANGED",
                "An upload key was already used. Remove the pending file and select it again.",
            )
        if staged.entity_id != req.entity_id or staged.expires_at <= datetime.now(UTC):
            raise DomainError(
                "DOCUMENTS_CHANGED",
                "A document expired or belongs to another company. Remove it and select it again.",
            )
        key = f"requisitions/{req.requester_id}/{req.creation_key}/{staged.id}/{staged.digest}"
        version = await storage.put(key, staged.data, staged.media_type)
        file = Attachment(
            id=staged.id,
            requisition_id=req.id,
            uploaded_by=req.requester_id,
            upload_key=staged.id,
            kind="request_support",
            filename=staged.filename,
            media_type=staged.media_type,
            byte_size=len(staged.data),
            digest=staged.digest,
            storage_key=key,
            object_version=version,
            validation_state="validated",
        )
        s.add(file)
        await s.delete(staged)
        await s.flush()
        await record_event(
            s,
            action="evidence.uploaded",
            actor_id=req.requester_id,
            resource_id=file.id,
            entity_id=req.entity_id,
        )
