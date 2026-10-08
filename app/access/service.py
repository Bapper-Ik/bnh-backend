from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, exists, false, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.access.models import ReviewGrant
from app.access.principal import Principal
from app.board.models import ChairmanDecision, Resolution
from app.core.errors import DomainError
from app.evidence.models import Attachment
from app.identity.models import Account
from app.identity.service import Actor
from app.organisation.models import Department, Entity, Membership, Office
from app.organisation.service import eligible_offices, membership, officeholder
from app.requisitions.models import Requisition, Revision

Action = Literal[
    "read",
    "edit",
    "revise",
    "submit",
    "approve",
    "reject",
    "return",
    "board_record",
    "board_confirm",
    "board_return",
    "attachment_upload",
    "export",
]


def request_scope(actor: Principal, *, inbox: bool = False) -> ColumnElement[bool]:
    now = datetime.now(UTC)
    pending_board = exists(
        select(Resolution.id).where(
            Resolution.revision_id == Revision.id,
            Resolution.signature != {},
            ~exists(
                select(ChairmanDecision.id).where(ChairmanDecision.resolution_id == Resolution.id)
            ),
        )
    ).correlate(Revision)
    board_role = and_(
        Revision.authority == "board",
        or_(
            and_(
                Office.role == "secretary",
                Revision.context["route"]["secretary_id"].astext == str(actor.id),
                ~pending_board if inbox else true(),
            ),
            and_(
                Office.role == "chairman",
                Revision.context["route"]["chairman_id"].astext == str(actor.id),
                pending_board if inbox else true(),
            ),
        ),
    )
    offices = (
        exists(
            select(Office.id)
            .join(
                Membership,
                (Membership.identity_id == Office.identity_id)
                & (Membership.entity_id == Office.entity_id),
            )
            .join(Department, Department.id == Membership.department_id)
            .join(Entity, Entity.id == Office.entity_id)
            .where(
                Requisition.state != "DRAFT",
                or_(Requisition.requester_id != actor.id, board_role),
                Office.identity_id == actor.id,
                Office.entity_id == Requisition.entity_id,
                Office.active.is_(True),
                Membership.active.is_(True),
                Department.active.is_(True),
                Entity.active.is_(True),
                Office.valid_from <= now,
                or_(Office.valid_until.is_(None), Office.valid_until > now),
                or_(Office.role != "hod", Office.department_id == Membership.department_id),
                or_(
                    board_role,
                    and_(
                        Revision.approver_id == actor.id,
                        Office.role == Revision.authority,
                        or_(
                            Office.role != "hod", Office.department_id == Requisition.department_id
                        ),
                    ),
                ),
            )
        ).correlate(Requisition, Revision)
        if not actor.account.read_only
        else false()
    )
    if inbox:
        eligible_count = (
            select(func.count(Office.id))
            .join(Account, Account.identity_id == Office.identity_id)
            .join(
                Membership,
                (Membership.identity_id == Office.identity_id)
                & (Membership.entity_id == Office.entity_id),
            )
            .join(Department, Department.id == Membership.department_id)
            .join(Entity, Entity.id == Office.entity_id)
            .where(
                Office.entity_id == Requisition.entity_id,
                Office.role == Revision.authority,
                or_(Office.role != "hod", Office.department_id == Requisition.department_id),
                or_(Office.role != "hod", Office.department_id == Membership.department_id),
                Office.active.is_(True),
                Office.valid_from <= now,
                or_(Office.valid_until.is_(None), Office.valid_until > now),
                Account.active.is_(True),
                Account.read_only.is_(False),
                Account.password_pending.is_(False),
                Membership.active.is_(True),
                Department.active.is_(True),
                Entity.active.is_(True),
            )
            .correlate(Requisition, Revision)
            .scalar_subquery()
        )
        return and_(
            offices,
            or_(
                and_(
                    Revision.authority == "board",
                    *[
                        select(func.count())
                        .select_from(
                            eligible_offices()
                            .where(Office.entity_id == Requisition.entity_id, Office.role == role)
                            .correlate(Requisition)
                            .subquery()
                        )
                        .scalar_subquery()
                        == 1
                        for role in ("secretary", "chairman")
                    ],
                ),
                eligible_count == 1,
            ),
            Requisition.state.in_(
                [
                    "PENDING_AUTHORITY",
                    "AWAITING_BOARD_RESOLUTION",
                    "AWAITING_CHAIRMAN_SIGNOFF",
                    "DEFERRED",
                    "CONDITIONALLY_APPROVED",
                ]
            ),
        )
    reviewer = (
        exists(
            select(ReviewGrant.id).where(
                ReviewGrant.identity_id == actor.id,
                ReviewGrant.entity_id == Requisition.entity_id,
                ReviewGrant.active.is_(True),
            )
        ).correlate(Requisition)
        if actor.account.read_only
        else false()
    )
    return or_(Requisition.requester_id == actor.id, offices, reviewer)


async def can_read(session: AsyncSession, req: Requisition, actor: Actor) -> bool:
    return bool(
        await session.scalar(
            select(Requisition.id)
            .outerjoin(Revision, Revision.id == Requisition.current_revision_id)
            .where(Requisition.id == req.id, request_scope(actor))
        )
    )


async def get_scoped_request(session: AsyncSession, request_id: UUID, actor: Actor) -> Requisition:
    req = await session.scalar(
        select(Requisition).where(Requisition.id == request_id).with_for_update()
    )
    if not req or not await can_read(session, req, actor):
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Requisition not found.", 404)
    return req


async def require_action(
    session: AsyncSession,
    req: Requisition,
    actor: Actor,
    action: Action,
    *,
    recorded_by: UUID | None = None,
) -> None:
    if not await can_read(session, req, actor):
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Requisition not found.", 404)
    if action in {"read", "export"}:
        return
    if actor.account.read_only:
        raise DomainError(
            "ACCESS_DENIED", "Read-only reviewers cannot change or sign records.", 403
        )
    if action in {"edit", "submit", "attachment_upload", "revise"}:
        allowed_state = "RETURNED_FOR_REVISION" if action == "revise" else "DRAFT"
        if req.requester_id == actor.id and req.state == allowed_state:
            current = await membership(session, actor.id, req.entity_id)
            if current.department_id == req.department_id:
                return
    elif action in {"approve", "reject", "return"}:
        if req.requester_id == actor.id:
            raise DomainError(
                "SELF_APPROVAL_PROHIBITED", "You cannot approve your own requisition."
            )
        if (
            req.state == "PENDING_AUTHORITY"
            and req.current_revision_id
            and req.requester_id != actor.id
        ):
            revision = await session.get(Revision, req.current_revision_id)
            if revision and revision.authority != "board":
                office = await officeholder(
                    session, req.entity_id, revision.authority, req.department_id
                )
                if office.identity_id == actor.id and revision.approver_id == actor.id:
                    return
    elif action in {"board_record", "board_confirm", "board_return"}:
        from app.board.service import available, board_access, records

        _, role, _ = await board_access(session, req, actor)
        actions = await available(session, req, role, await records(session, req))
        if action == "board_record" and set(actions).intersection(
            {"create", "correct", "later_resolution", "edit"}
        ):
            return
        if action in {"board_confirm", "board_return"} and action in actions:
            return
    raise DomainError(
        "ACCESS_DENIED", "Your current role and this record do not permit that action.", 403
    )


async def require_attachment(
    session: AsyncSession, attachment_id: UUID, actor: Actor
) -> Attachment:
    attachment = await session.get(Attachment, attachment_id)
    if not attachment or attachment.detached:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Attachment not found.", 404)
    req = await get_scoped_request(session, attachment.requisition_id, actor)
    if attachment.kind == "board_resolution":
        from app.board.service import board_access

        await board_access(session, req, actor)
    return attachment


def project_content(
    content: dict[str, object], actor: Actor
) -> tuple[dict[str, object], list[str]]:
    if not actor.account.read_only:
        return content, []
    projected = dict(content)
    vendor = content.get("vendor")
    if isinstance(vendor, dict):
        projected["vendor"] = {**vendor, "bank_name": "", "account_number": "", "account_name": ""}
    return projected, ["vendor.bank_details"]
