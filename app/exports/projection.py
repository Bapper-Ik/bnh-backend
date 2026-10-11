from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.service import project_content
from app.board.models import ChairmanDecision, Resolution
from app.board.service import OUTCOMES, board_access
from app.core.database import Identity
from app.core.errors import DomainError
from app.evidence.models import Attachment
from app.exports.schemas import (
    BoardRecord,
    EvidenceReference,
    ExportCommand,
    SigningRecord,
    Snapshot,
)
from app.identity.service import Actor
from app.organisation.models import Department, Entity
from app.requisitions.models import Decision, Requisition, Revision
from app.requisitions.schemas import Content
from app.requisitions.service import attachment_manifest, get_revision


def signing(label: str, data: dict[str, Any], reason: str = "") -> SigningRecord:
    return SigningRecord(
        label=label,
        name=str(data["name"]),
        at=str(data["at"]),
        statement=str(data.get("declaration", "")),
        reason=reason,
        digest=str(data.get("content_digest", "")),
        signature_id=str(data.get("challenge_id", "")),
        strokes=data.get("strokes", []),
    )


async def capture(
    s: AsyncSession, req: Requisition, actor: Actor, command: ExportCommand
) -> tuple[Snapshot, Revision | None]:
    rev = (
        await get_revision(s, req, command.revision)
        if command.revision
        else (
            await s.get(Revision, req.current_revision_id)
            if req.state != "DRAFT" and req.current_revision_id
            else None
        )
    )
    if command.include_board:
        current, _, _ = await board_access(s, req, actor)
        if not rev or current.id != rev.id:
            raise DomainError(
                "RESOURCE_NOT_AVAILABLE",
                "Private Board records are unavailable for this revision.",
                404,
            )
    body, redacted = project_content(rev.content if rev else req.content, actor)
    original_context = rev.context.get("context", {}) if rev else req.context
    if (
        isinstance(original_context, dict)
        and original_context.get("bank_details_state") == "restricted"
    ):
        redacted = ["vendor.bank_details"]
    content = Content.model_validate(body)
    if redacted:
        content.vendor.bank_name = content.vendor.account_name = content.vendor.account_number = ""
    person, entity, department = (
        await s.get(Identity, req.requester_id),
        await s.get(Entity, req.entity_id),
        await s.get(Department, req.department_id),
    )
    assert person and entity and department
    snapshot = Snapshot(
        reference=req.reference,
        requisition_id=req.id,
        revision=rev.number if rev else 0,
        request_version=req.version,
        state="DRAFT",
        current_state=req.state,
        requester=rev.requester_name if rev else person.display_name,
        department=rev.department_name if rev else department.name,
        company=rev.entity_name if rev else entity.name,
        authority=rev.authority if rev else "",
        route=rev.routing_explanation if rev else "",
        policy=rev.policy_version if rev else "",
        content=content,
        total=format(rev.total if rev else req.total, ".2f"),
        redacted_fields=redacted,
        as_of=datetime.now(UTC),
        signatures=[],
        evidence=[],
        board=[],
        include_board=command.include_board,
    )
    manifest = rev.context.get("attachments", []) if rev else await attachment_manifest(s, req)
    if isinstance(manifest, list):
        snapshot.evidence = [
            EvidenceReference(id=str(f["id"]), filename=str(f["filename"]), digest=str(f["digest"]))
            for f in manifest
            if isinstance(f, dict)
        ]
    if not rev:
        return snapshot, None
    snapshot.signatures.append(signing("Requester declaration", rev.signature))
    decision = await s.scalar(select(Decision).where(Decision.revision_id == rev.id))
    snapshot.state = "PENDING_AUTHORITY"
    if decision:
        snapshot.state = {
            "approve": "APPROVED",
            "reject": "REJECTED",
            "return": "RETURNED_FOR_REVISION",
        }[decision.action]
        snapshot.signatures.append(
            signing(
                {"approve": "Approval", "reject": "Rejection", "return": "Returned for revision"}[
                    decision.action
                ],
                decision.signature,
                decision.reason,
            )
        )
    if rev.authority != "board":
        return snapshot, rev
    rows = (
        await s.execute(
            select(Resolution, ChairmanDecision)
            .outerjoin(ChairmanDecision, ChairmanDecision.resolution_id == Resolution.id)
            .where(Resolution.revision_id == rev.id, Resolution.signature != {})
            .order_by(Resolution.number)
            .limit(201)
        )
    ).all()
    if len(rows) > 200:
        raise DomainError("EXPORT_TOO_LARGE", "This history is too large for a single export.", 422)
    snapshot.state = "AWAITING_BOARD_RESOLUTION"
    for record, confirmed in rows:
        if confirmed and confirmed.action == "board_confirm":
            snapshot.state = OUTCOMES[confirmed.outcome]
            # Requester/reviewer gets the same public outcome/name/time as request history.
            if not command.include_board:
                snapshot.signatures.append(
                    SigningRecord(
                        label="Board outcome confirmed: " + confirmed.outcome.replace("_", " "),
                        name=str(confirmed.signature["name"]),
                        at=str(confirmed.signature["at"]),
                    )
                )
        elif not confirmed and snapshot.state not in {"DEFERRED", "CONDITIONALLY_APPROVED"}:
            snapshot.state = "AWAITING_CHAIRMAN_SIGNOFF"
        if command.include_board:
            data = record.data
            evidence = await s.get(Attachment, record.evidence_id) if record.evidence_id else None
            records = [signing("Secretary: Board record submitted", record.signature)]
            if confirmed:
                records.append(
                    signing(
                        "Chairman: "
                        + (
                            "returned to Secretary"
                            if confirmed.action == "board_return"
                            else "confirmed " + confirmed.outcome.replace("_", " ")
                        ),
                        confirmed.signature,
                        confirmed.reason,
                    )
                )
            snapshot.board.append(
                BoardRecord(
                    number=record.number,
                    kind=record.kind,
                    record_id=str(record.id),
                    predecessor_id=str(record.predecessor_id) if record.predecessor_id else None,
                    recorded_at=record.created_at.isoformat(),
                    meeting_date=str(data["meeting_date"]),
                    reference=str(data["reference"]),
                    board_name=str(data["board_name"]),
                    outcome=str(data["outcome"]),
                    decision=str(data["decision_text"]),
                    amount=str(data["authorised_amount"])
                    if data.get("authorised_amount") is not None
                    else None,
                    conditions=str(data.get("conditions", "")),
                    attendance=str(data.get("attendance", "")),
                    quorum_basis=str(data.get("quorum_basis", "")),
                    correction=str(data.get("correction_summary", "")),
                    evidence=EvidenceReference(
                        id=str(evidence.id), filename=evidence.filename, digest=evidence.digest
                    )
                    if evidence
                    else None,
                    signatures=records,
                )
            )
    return snapshot, rev
