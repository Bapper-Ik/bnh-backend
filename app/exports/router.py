from datetime import UTC, datetime
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.access.service import get_scoped_request
from app.audit.read import board_requests
from app.core.database import get_session
from app.core.errors import DomainError
from app.exports.models import Export
from app.exports.schemas import ExportCommand, ExportPage, ExportView
from app.exports.service import audit, enqueue, present
from app.exports.worker import scoped
from app.identity.service import Actor, current_actor
from app.notifications.service import Recipient
from app.requisitions.models import Requisition

router = APIRouter(prefix="/api/v1", tags=["Exports"])


async def unavailable(request: Request) -> str | None:
    if not request.app.state.uploads_enabled:
        return "Private document storage must be configured before generating PDFs."
    if not await run_in_threadpool(request.app.state.export_fonts_available):
        return "The bundled PDF fonts are unavailable. Please contact your administrator to repair the backend deployment."
    return None


async def get_export(s: AsyncSession, actor: Actor, export_id: UUID) -> Export:
    row = await s.scalar(
        scoped(Recipient(actor.account)).where(Export.id == export_id).with_for_update(of=Export)
    )
    if not row:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Export not found.", 404)
    return row


@router.get("/requisitions/{request_id}/exports", response_model=ExportPage)
async def list_exports(
    request_id: UUID,
    request: Request,
    revision: int | None = Query(default=None, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=2147483647),
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> ExportPage:
    req = await get_scoped_request(s, request_id, actor)
    query = scoped(Recipient(actor.account)).where(Export.requisition_id == req.id)
    if revision is not None:
        query = query.where(Export.revision_number == revision)
    total = await s.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (
        await s.scalars(
            query.order_by(Export.created_at.desc(), Export.id.desc()).limit(limit).offset(offset)
        )
    ).all()
    can_board = (
        bool(await s.scalar(board_requests(actor).where(Requisition.id == req.id)))
        and req.state != "DRAFT"
    )
    return ExportPage(
        items=[present(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
        can_include_board=can_board,
        unavailable_reason=await unavailable(request),
    )


@router.post("/requisitions/{request_id}/exports", response_model=ExportView, status_code=202)
async def create_export(
    request_id: UUID,
    body: ExportCommand,
    request: Request,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> ExportView:
    req = await get_scoped_request(s, request_id, actor)
    reason = await unavailable(request)
    if reason:
        raise DomainError("SERVICE_UNAVAILABLE", reason, 503)
    row = await enqueue(s, req, actor, body)
    # Replays must pass current bank/Board scope as well as matching the original payload.
    return present(await get_export(s, actor, row.id))


@router.get("/exports/{export_id}", response_model=ExportView)
async def metadata(
    export_id: UUID,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> ExportView:
    return present(await get_export(s, actor, export_id))


@router.post("/exports/{export_id}/retry", response_model=ExportView)
async def retry(
    export_id: UUID,
    request: Request,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> ExportView:
    row = await get_export(s, actor, export_id)
    if row.last_error == "transfer_details_missing":
        raise DomainError(
            "TRANSFER_DETAILS_MISSING",
            "The signed approval did not contain complete bank details. They cannot be added to a signed transfer request.",
            409,
        )
    if row.status == "failed":
        reason = await unavailable(request)
        if reason:
            raise DomainError("SERVICE_UNAVAILABLE", reason, 503)
        row.status, row.attempts, row.last_error = "pending", 0, None
        row.available_at = datetime.now(UTC)
        await audit(s, row, "queued")
    return present(row)


@router.get("/exports/{export_id}/content")
async def download(
    export_id: UUID,
    request: Request,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> Response:
    row = await get_export(s, actor, export_id)
    if row.status != "ready" or not row.storage_key or not row.file_digest or row.byte_size is None:
        raise DomainError(
            "EXPORT_NOT_READY", "This PDF is not ready. Check its generation status.", 409
        )
    data = await request.app.state.evidence_storage.get(
        row.storage_key, row.file_digest, row.byte_size
    )
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(row.filename, safe=""),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )
