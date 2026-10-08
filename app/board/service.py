from datetime import datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.board.models import ChairmanDecision, Resolution
from app.board.schemas import BoardCase, BoardIntent, ResolutionData, ResolutionView
from app.core.errors import DomainError
from app.evidence.models import Attachment
from app.evidence.router import view as attachment_view
from app.identity.service import Actor
from app.organisation.service import officeholder
from app.requisitions.models import Requisition, Revision
from app.requisitions.service import present

OUTCOMES = {
    "APPROVE": "APPROVED",
    "REJECT": "REJECTED",
    "DEFER": "DEFERRED",
    "CONDITIONAL_APPROVE": "CONDITIONALLY_APPROVED",
}
HOLDS = {"DEFERRED", "CONDITIONALLY_APPROVED"}
STATEMENTS = {
    "board_submit": "I attest that this record and its evidence accurately represent the actual Board meeting and resolution, including the outcome, attendance and quorum basis recorded here.",
    "board_confirm": "I have reviewed the Secretary's signed record and formal evidence and confirm this exact Board resolution and its recorded outcome.",
    "board_return": "I have reviewed this Board record and return it to the Company Secretary for the stated correction. This does not return the requisition to its requester.",
}


async def board_access(
    s: AsyncSession, req: Requisition, actor: Actor
) -> tuple[Revision, str, dict[str, str]]:
    rev = await s.get(Revision, req.current_revision_id) if req.current_revision_id else None
    if not rev or rev.authority != "board" or actor.account.read_only:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Board case not found.", 404)
    route = rev.context.get("route")
    if not isinstance(route, dict) or str(actor.id) not in {
        route.get("secretary_id"),
        route.get("chairman_id"),
    }:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Board case not found.", 404)
    secretary = await officeholder(s, req.entity_id, "secretary")
    chairman = await officeholder(s, req.entity_id, "chairman")
    if str(secretary.identity_id) != route.get("secretary_id") or str(
        chairman.identity_id
    ) != route.get("chairman_id"):
        raise DomainError(
            "AUTHORITY_ASSIGNMENT_BLOCKED",
            "A Board assignment has changed. The originally assigned current Secretary and Chairman are required.",
        )
    if secretary.identity_id == chairman.identity_id or chairman.identity_id == req.requester_id:
        raise DomainError(
            "BOARD_SEPARATION_REQUIRED",
            "The Chairman must differ from the Secretary and requester.",
        )
    return (
        rev,
        "secretary" if actor.id == secretary.identity_id else "chairman",
        {"secretary": str(secretary.id), "chairman": str(chairman.id)},
    )


async def records(s: AsyncSession, req: Requisition) -> list[Resolution]:
    return list(
        (
            await s.scalars(
                select(Resolution)
                .where(Resolution.revision_id == req.current_revision_id)
                .order_by(Resolution.number)
            )
        ).all()
    )


async def decision(s: AsyncSession, record: Resolution) -> ChairmanDecision | None:
    result = await s.scalar(
        select(ChairmanDecision).where(ChairmanDecision.resolution_id == record.id)
    )
    return result


async def available(
    s: AsyncSession, req: Requisition, role: str, rows: list[Resolution]
) -> list[str]:
    if req.state in {"APPROVED", "REJECTED"}:
        return []
    last = rows[-1] if rows else None
    result = await decision(s, last) if last else None
    if role == "secretary":
        if not last:
            return ["create"] if req.state == "AWAITING_BOARD_RESOLUTION" else []
        if not last.signature:
            return ["edit", "board_submit"]
        if result and result.action == "board_return":
            return ["correct"]
        if result and req.state in HOLDS:
            return ["later_resolution"]
    elif last and last.signature and not result:
        return ["board_confirm", "board_return"]
    return []


async def case_view(
    s: AsyncSession, req: Requisition, actor: Actor, uploads_enabled: bool
) -> BoardCase:
    _, role, _ = await board_access(s, req, actor)
    rows = await records(s, req)
    views = []
    for row in rows:
        result = await decision(s, row)
        evidence = await s.get(Attachment, row.evidence_id) if row.evidence_id else None
        views.append(
            ResolutionView(
                id=row.id,
                number=row.number,
                predecessor_id=row.predecessor_id,
                kind=row.kind,
                data=ResolutionData.model_validate(row.data),
                status=(
                    "RETURNED_TO_SECRETARY"
                    if result.action == "board_return"
                    else OUTCOMES[result.outcome]
                )
                if result
                else "AWAITING_CHAIRMAN_SIGNOFF"
                if row.signature
                else "DRAFT",
                recorded_at=row.created_at.isoformat(),
                submitted_at=str(row.signature["at"]) if row.signature else None,
                secretary_name=str(row.signature["name"]) if row.signature else None,
                chairman_name=str(result.signature["name"]) if result else None,
                decided_at=result.created_at.isoformat() if result else None,
                return_reason=result.reason if result and result.action == "board_return" else None,
                evidence=attachment_view(evidence) if evidence else None,
            )
        )
    return BoardCase(
        request=await present(s, req, actor),
        records=views,
        available_actions=await available(s, req, role, rows),
        uploads_enabled=uploads_enabled,
    )


def version(req: Requisition, expected: int) -> None:
    if req.version != expected:
        raise DomainError(
            "REVISION_CONFLICT", "This Board case changed. Reload and review it again."
        )


async def editable(
    s: AsyncSession, req: Requisition, actor: Actor, resolution_id: UUID, expected: int
) -> Resolution:
    _, role, _ = await board_access(s, req, actor)
    rows = await records(s, req)
    if "edit" not in await available(s, req, role, rows) or rows[-1].id != resolution_id:
        raise DomainError(
            "ACCESS_DENIED", "Only the assigned Secretary may edit the latest unsigned record.", 403
        )
    version(req, expected)
    return rows[-1]


async def bound_intent(
    s: AsyncSession, req: Requisition, actor: Actor, resolution_id: UUID, body: BoardIntent
) -> tuple[Resolution, Attachment, dict[str, object]]:
    rev, role, appointments = await board_access(s, req, actor)
    rows = await records(s, req)
    if (
        not rows
        or rows[-1].id != resolution_id
        or body.action not in await available(s, req, role, rows)
    ):
        raise DomainError("ACCESS_DENIED", "This Board record does not permit that action.", 403)
    version(req, body.expected_version)
    record = rows[-1]
    if body.action != "board_submit" and actor.id in {record.recorded_by, req.requester_id}:
        raise DomainError(
            "BOARD_SEPARATION_REQUIRED", "The Chairman must differ from the recorder and requester."
        )
    if body.action == "board_return" and not body.reason.strip():
        raise DomainError(
            "VALIDATION_FAILED", "Explain the correction required from the Secretary.", 422
        )
    data = ResolutionData.model_validate(record.data)
    if body.action == "board_submit":
        if (
            not data.meeting_date
            or data.meeting_date > datetime.now(ZoneInfo("Africa/Lagos")).date()
        ):
            raise DomainError(
                "VALIDATION_FAILED", "Enter the actual meeting date, no later than today.", 422
            )
        if (
            not all(
                x.strip()
                for x in [
                    data.board_name,
                    data.reference,
                    data.decision_text,
                    data.attendance,
                    data.quorum_basis,
                ]
            )
            or not data.quorum_attested
        ):
            raise DomainError(
                "VALIDATION_FAILED",
                "Record the Board, resolution reference, decision, attendance and attested quorum basis.",
                422,
            )
        if data.outcome in {"APPROVE", "CONDITIONAL_APPROVE"} and (
            data.authorised_amount is None or Decimal(data.authorised_amount) != rev.total
        ):
            raise DomainError(
                "VALIDATION_FAILED",
                "The authorised amount must equal this exact requisition total.",
                422,
            )
        if data.outcome == "CONDITIONAL_APPROVE" and not data.conditions.strip():
            raise DomainError(
                "VALIDATION_FAILED",
                "Record the unresolved conditions for conditional approval.",
                422,
            )
        if record.kind == "correction" and not data.correction_summary.strip():
            raise DomainError(
                "VALIDATION_FAILED", "Explain the correction made to the returned record.", 422
            )
        if record.kind == "later_resolution" and record.predecessor_id:
            previous = await s.get(Resolution, record.predecessor_id)
            assert previous
            prior = ResolutionData.model_validate(previous.data)
            if prior.meeting_date and data.meeting_date < prior.meeting_date:
                raise DomainError(
                    "VALIDATION_FAILED",
                    "A later resolution cannot precede the earlier meeting.",
                    422,
                )
            if data.reference.strip() == prior.reference.strip():
                raise DomainError(
                    "VALIDATION_FAILED",
                    "Use the reference of the new actual Board resolution.",
                    422,
                )
    evidence = await s.get(Attachment, record.evidence_id) if record.evidence_id else None
    if (
        not evidence
        or evidence.kind != "board_resolution"
        or evidence.requisition_id != req.id
        or evidence.detached
        or evidence.validation_state != "validated"
    ):
        raise DomainError(
            "VALIDATION_FAILED", "Attach a formal resolution or authenticated minutes extract.", 422
        )
    if req.content != rev.content or req.total != rev.total:
        raise DomainError(
            "REVISION_CONFLICT", "The requisition no longer matches its signed revision."
        )
    bound = {
        "request_id": str(req.id),
        "revision_id": str(rev.id),
        "revision_digest": rev.content_digest,
        "resolution_id": str(record.id),
        "number": record.number,
        "predecessor_id": str(record.predecessor_id),
        "recorded_by": str(record.recorded_by),
        "data": record.data,
        "secretary_signature": record.signature,
        "version": req.version,
        "actor_id": str(actor.id),
        "action": body.action,
        "reason": body.reason,
        "appointments": appointments,
        "evidence": {
            "id": str(evidence.id),
            "digest": evidence.digest,
            "object_version": evidence.object_version,
        },
        "declaration": STATEMENTS[body.action],
        "declaration_version": "board-v1",
    }
    return record, evidence, bound
