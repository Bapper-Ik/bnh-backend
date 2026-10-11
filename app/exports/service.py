from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import and_, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.access.principal import Principal
from app.access.service import request_scope
from app.audit.read import board_requests
from app.audit.service import AuditDetails, record_event
from app.core.errors import DomainError
from app.exports.models import Export
from app.exports.projection import capture
from app.exports.render import TEMPLATE_VERSION
from app.exports.schemas import ExportCommand, ExportView
from app.identity.service import Actor
from app.requisitions.models import Requisition
from app.requisitions.router import key_lock
from app.requisitions.service import content_digest


def allowed(actor: Principal) -> ColumnElement[bool]:
    return and_(
        Export.requested_by == actor.id,
        request_scope(actor),
        or_(
            Export.includes_bank.is_(False),
            false() if actor.account.read_only else Export.includes_bank.is_(True),
        ),
        or_(Export.include_board.is_(False), Requisition.id.in_(board_requests(actor))),
    )


def present(row: Export) -> ExportView:
    return ExportView(
        id=row.id,
        document_type=row.document_type,
        revision=row.revision_number,
        request_version=row.request_version,
        include_board=row.include_board,
        filename=row.filename,
        status=row.status,
        created_at=row.created_at,
        generated_at=row.generated_at,
        template_version=row.template_version,
        file_digest=row.file_digest,
        byte_size=row.byte_size,
        attempts=row.attempts,
        last_error=row.last_error,
        can_retry=row.status == "failed" and row.last_error != "transfer_details_missing",
    )


async def enqueue(
    s: AsyncSession, req: Requisition, actor: Actor, command: ExportCommand
) -> Export:
    await key_lock(s, actor, command.idempotency_key)
    digest = content_digest({"request_id": str(req.id), **command.model_dump(mode="json")})
    existing = await s.scalar(
        select(Export).where(
            Export.requested_by == actor.id, Export.idempotency_key == command.idempotency_key
        )
    )
    if existing:
        if existing.command_digest != digest:
            raise DomainError(
                "IDEMPOTENCY_CONFLICT", "This export key was already used for different content."
            )
        return existing
    if command.expected_version != req.version:
        raise DomainError(
            "REVISION_CONFLICT", "The request changed. Reload it before generating a PDF."
        )
    snapshot, rev = await capture(s, req, actor, command)
    payload = snapshot.model_dump(mode="json")
    if len(str(payload)) > 2_000_000:
        raise DomainError("EXPORT_TOO_LARGE", "This record is too large for a single export.", 422)
    row = Export(
        id=uuid4(),
        requisition_id=req.id,
        revision_id=rev.id if rev else None,
        requested_by=actor.id,
        idempotency_key=command.idempotency_key,
        command_digest=digest,
        request_version=req.version,
        revision_number=rev.number if rev else 0,
        include_board=command.include_board,
        includes_bank=any(
            (
                snapshot.content.vendor.bank_name,
                snapshot.content.vendor.account_name,
                snapshot.content.vendor.account_number,
            )
        ),
        snapshot=payload,
        snapshot_digest=content_digest(payload),
        template_version=TEMPLATE_VERSION,
        filename=f"{req.reference}-"
        + (f"revision-{rev.number}" if rev else f"draft-v{req.version}")
        + ("-board" if command.include_board else "")
        + ".pdf",
        available_at=datetime.now(UTC),
    )
    s.add(row)
    await s.flush()
    await audit(s, row, "queued")
    return row


async def audit(s: AsyncSession, row: Export, outcome: str) -> None:
    req = await s.get(Requisition, row.requisition_id)
    assert req
    await record_event(
        s,
        action="requisition.export." + outcome,
        actor_id=row.requested_by,
        resource_id=req.id,
        entity_id=req.entity_id,
        details=AuditDetails(
            resource_type="export",
            export_id=row.id,
            revision_id=row.revision_id,
            outcome="denied" if outcome == "failure" else "success",
        ),
    )
