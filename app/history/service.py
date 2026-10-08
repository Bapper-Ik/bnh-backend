from sqlalchemy import String, cast, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.board.models import ChairmanDecision, Resolution
from app.core.database import Identity
from app.core.errors import DomainError
from app.evidence.models import Attachment
from app.history.schemas import HistoryEntry, HistoryPage, NextAction
from app.identity.service import Actor
from app.organisation.service import officeholder
from app.requisitions.models import Decision, Requisition, Revision


def payload(**fields: object):  # type: ignore[no-untyped-def]
    args = []
    for key, value in fields.items():
        args.extend([literal(key), value])
    return func.jsonb_build_object(*args)


async def board_visible(s: AsyncSession, req: Requisition, actor: Actor) -> bool:
    from app.board.service import board_access

    try:
        await board_access(s, req, actor)
        return True
    except DomainError:
        return False


async def history_page(
    s: AsyncSession,
    req: Requisition,
    actor: Actor,
    *,
    limit: int = 50,
    offset: int = 0,
    revision: int | None = None,
) -> HistoryPage:
    """Project actual events in SQL and paginate before fetching any signed payloads."""
    rev_filter = [Revision.requisition_id == req.id]
    if revision is not None:
        rev_filter.append(Revision.number == revision)
    submissions = select(
        Revision.created_at.label("at"),
        (literal("submission:") + cast(Revision.id, String)).label("id"),
        payload(
            type="submission",
            at=Revision.created_at,
            actor=Revision.requester_name,
            actor_id=Revision.signature["actor_id"].astext,
            revision=Revision.number,
            authority=Revision.authority,
            routing_explanation=Revision.routing_explanation,
            policy_version=Revision.policy_version,
            digest=Revision.content_digest,
            signature_id=Revision.signature["challenge_id"].astext,
        ).label("data"),
    ).where(*rev_filter)
    decisions = (
        select(
            Decision.created_at,
            literal("decision:") + cast(Decision.id, String),
            payload(
                type=Decision.action,
                at=Decision.created_at,
                actor=func.coalesce(Decision.signature["name"].astext, Identity.display_name),
                actor_id=Decision.actor_id,
                revision=Revision.number,
                reason=Decision.reason,
                authority=Revision.authority,
                digest=Decision.content_digest,
                signature_id=Decision.signature["challenge_id"].astext,
            ),
        )
        .join(Revision, Revision.id == Decision.revision_id)
        .join(Identity, Identity.id == Decision.actor_id)
        .where(*rev_filter)
    )
    general = (
        select(
            AuditEvent.created_at,
            literal("event:") + cast(AuditEvent.id, String),
            payload(
                type=AuditEvent.action,
                at=AuditEvent.created_at,
                actor=func.coalesce(Identity.display_name, "System"),
                actor_id=AuditEvent.actor_id,
            ),
        )
        .outerjoin(Identity, Identity.id == AuditEvent.actor_id)
        .where(
            AuditEvent.resource_id == req.id,
            AuditEvent.action.in_(
                ["requisition.created", "requisition.updated", "requisition.revision_created"]
            ),
        )
    )
    queries = [submissions, decisions]
    if revision is None:
        queries.append(general)
    private = await board_visible(s, req, actor)
    fields: dict[str, object] = {}
    if private:
        fields = dict(
            resolution_id=Resolution.id,
            resolution_number=Resolution.number,
            resolution_reference=Resolution.data["reference"].astext,
            meeting_date=Resolution.data["meeting_date"].astext,
            evidence_id=Attachment.id,
            evidence_filename=Attachment.filename,
        )
        recorded = (
            select(
                Resolution.created_at,
                literal("board_record:") + cast(Resolution.id, String),
                payload(
                    type="board_recorded",
                    at=Resolution.created_at,
                    actor=Identity.display_name,
                    actor_id=Resolution.recorded_by,
                    revision=Revision.number,
                    authority="board",
                    **fields,
                ),
            )
            .join(Revision, Revision.id == Resolution.revision_id)
            .join(Identity, Identity.id == Resolution.recorded_by)
            .outerjoin(Attachment, Attachment.id == Resolution.evidence_id)
            .where(*rev_filter)
        )
        queries.append(recorded)
        recordings = (
            select(
                cast(Resolution.signature["at"].astext, AuditEvent.created_at.type),
                literal("board_submission:") + cast(Resolution.id, String),
                payload(
                    type="board_submitted",
                    at=Resolution.signature["at"].astext,
                    actor=Resolution.signature["name"].astext,
                    actor_id=Resolution.recorded_by,
                    revision=Revision.number,
                    authority="board",
                    signature_id=Resolution.signature["challenge_id"].astext,
                    digest=Resolution.signature["content_digest"].astext,
                    **fields,
                ),
            )
            .join(Revision, Revision.id == Resolution.revision_id)
            .outerjoin(Attachment, Attachment.id == Resolution.evidence_id)
            .where(*rev_filter, Resolution.signature != {})
        )
        queries.append(recordings)
    board_decisions = (
        select(
            ChairmanDecision.created_at,
            literal("board_decision:") + cast(ChairmanDecision.id, String),
            payload(
                type=func.concat("board_", func.lower(ChairmanDecision.outcome)),
                at=ChairmanDecision.created_at,
                actor=ChairmanDecision.signature["name"].astext,
                actor_id=ChairmanDecision.actor_id,
                revision=Revision.number,
                authority="board",
                signature_id=ChairmanDecision.signature["challenge_id"].astext if private else None,
                digest=ChairmanDecision.signature["content_digest"].astext if private else None,
                **fields,
            ),
        )
        .select_from(ChairmanDecision)
        .join(Resolution, Resolution.id == ChairmanDecision.resolution_id)
        .join(Revision, Revision.id == Resolution.revision_id)
        .outerjoin(Attachment, Attachment.id == Resolution.evidence_id)
        .where(*rev_filter, ChairmanDecision.action == "board_confirm")
    )
    queries.append(board_decisions)
    if private:
        returns = (
            select(
                ChairmanDecision.created_at,
                literal("board_return:") + cast(ChairmanDecision.id, String),
                payload(
                    type="board_return",
                    at=ChairmanDecision.created_at,
                    actor=ChairmanDecision.signature["name"].astext,
                    actor_id=ChairmanDecision.actor_id,
                    revision=Revision.number,
                    reason=ChairmanDecision.reason,
                    authority="board",
                    signature_id=ChairmanDecision.signature["challenge_id"].astext,
                    digest=ChairmanDecision.signature["content_digest"].astext,
                    **fields,
                ),
            )
            .select_from(ChairmanDecision)
            .join(Resolution, Resolution.id == ChairmanDecision.resolution_id)
            .join(Revision, Revision.id == Resolution.revision_id)
            .outerjoin(Attachment, Attachment.id == Resolution.evidence_id)
            .where(*rev_filter, ChairmanDecision.action == "board_return")
        )
        queries.append(returns)
    events = union_all(*queries).subquery()
    count = await s.scalar(select(func.count()).select_from(events))
    rows = (
        await s.execute(
            select(events).order_by(events.c.at, events.c.id).limit(limit).offset(offset)
        )
    ).all()
    return HistoryPage(
        items=[HistoryEntry.model_validate({**row.data, "id": row.id}) for row in rows],
        total=count or 0,
        limit=limit,
        offset=offset,
    )


async def next_action(s: AsyncSession, req: Requisition, rev: Revision | None) -> NextAction:
    if req.state in {"DRAFT", "RETURNED_FOR_REVISION"}:
        person = await s.get(Identity, req.requester_id)
        return NextAction(
            label="Complete and submit the draft"
            if req.state == "DRAFT"
            else "Correct and resubmit the requisition",
            actor_name=person.display_name if person else None,
        )
    if req.state in {"APPROVED", "REJECTED"}:
        return NextAction(label="No further approval action")
    if not rev:
        return NextAction(
            label="Review required", blocked_reason="No submitted revision is available."
        )
    role = rev.authority
    route = rev.context.get("route", {})
    expected = str(rev.approver_id)
    label = "Review and decide the requisition"
    if role == "board":
        latest = await s.scalar(
            select(Resolution)
            .where(Resolution.revision_id == rev.id)
            .order_by(Resolution.number.desc())
            .limit(1)
        )
        decided = (
            await s.scalar(
                select(ChairmanDecision.id).where(ChairmanDecision.resolution_id == latest.id)
            )
            if latest
            else None
        )
        role = "chairman" if latest and latest.signature and not decided else "secretary"
        expected = str(route.get(role + "_id")) if isinstance(route, dict) else ""
        label = (
            "Review the Secretary's signed Board record"
            if role == "chairman"
            else "Record the Board meeting resolution"
        )
        if req.state in {"DEFERRED", "CONDITIONALLY_APPROVED"}:
            label = "Hold remains: " + (
                "review the later Board record"
                if role == "chairman"
                else "record a later Board resolution"
            )
    try:
        if rev.authority == "board":
            for board_role in ("secretary", "chairman"):
                assigned = await officeholder(s, req.entity_id, board_role)
                if not isinstance(route, dict) or str(assigned.identity_id) != route.get(
                    board_role + "_id"
                ):
                    raise DomainError(
                        "AUTHORITY_ASSIGNMENT_BLOCKED",
                        "A Board assignment has changed. The originally assigned current Secretary and Chairman are required.",
                    )
        office = await officeholder(s, req.entity_id, role, req.department_id)
        if str(office.identity_id) != expected:
            raise DomainError(
                "AUTHORITY_ASSIGNMENT_BLOCKED",
                "The assigned person no longer holds the required office. Contact your administrator.",
            )
        person = await s.get(Identity, office.identity_id)
        return NextAction(label=label, actor_name=person.display_name if person else None)
    except DomainError as exc:
        return NextAction(label=label, blocked_reason=exc.message)
