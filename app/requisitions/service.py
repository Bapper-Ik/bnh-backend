import hashlib
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.service import project_content, require_action
from app.authority.policy import calculate_lines, resolve
from app.core.database import Identity
from app.core.errors import DomainError
from app.evidence.models import Attachment
from app.identity.service import Actor
from app.organisation.models import Department, Entity
from app.organisation.service import active_offices, membership, officeholder
from app.requisitions.models import Decision, Requisition, Revision
from app.requisitions.schemas import (
    Content,
    CreateRequest,
    Intent,
    RequestView,
    UpdateRequest,
    VendorInfo,
)
from app.vendors.models import VendorVersion
from app.vendors.service import scoped_vendor
from app.vendors.service import view as vendor_view

DECLARATION = "I confirm that all information provided is true and correct and work will be completed as specified."
DECLARATION_VERSION = "originator-v1"


def content_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def total_for(content: Content) -> str:
    return calculate_lines([(x.quantity, x.unit_price) for x in content.lines])[1]


async def authorise_intent(
    s: AsyncSession, req: Requisition, actor: Actor, intent: Intent
) -> dict[str, object]:
    await require_action(s, req, actor, intent.action)
    if req.version != intent.expected_version:
        raise DomainError(
            "REVISION_CONFLICT", "This request has changed. Reload and review it again."
        )
    requester_name = actor.identity.display_name
    route_data: dict[str, object] = {}
    if intent.action == "submit":
        if req.requester_id != actor.id or req.state != "DRAFT":
            raise DomainError("INVALID_STATE_TRANSITION", "This request cannot be submitted.")
        member = await membership(s, actor.id, req.entity_id)
        if member.department_id != req.department_id:
            raise DomainError(
                "AUTHORITY_ASSIGNMENT_BLOCKED",
                "Your department changed; create a request using the current assignment.",
            )
        content = Content.model_validate(req.content)
        if (
            not content.vendor.name.strip()
            or not content.description.strip()
            or not content.location.strip()
            or not content.lines
        ):
            raise DomainError(
                "VALIDATION_FAILED",
                "Vendor, description, location and at least one item are required.",
                422,
            )
        banks = [
            content.vendor.bank_name,
            content.vendor.account_number,
            content.vendor.account_name,
        ]
        if any(banks) and not all(banks):
            raise DomainError(
                "VALIDATION_FAILED",
                "Provide all three bank details or leave all explicitly unsupplied.",
                422,
            )
        appointments = [
            o for o in await active_offices(s, req.entity_id) if o.identity_id == actor.id
        ]
        offices = {o.role for o in appointments}
        route = resolve(total_for(content), offices)
        approver = None
        if route.authority.label == "board":
            secretary = await officeholder(s, req.entity_id, "secretary")
            chairman = await officeholder(s, req.entity_id, "chairman")
            if secretary.identity_id == chairman.identity_id:
                raise DomainError(
                    "BOARD_SEPARATION_REQUIRED", "Secretary and Chairman must be different people."
                )
            if chairman.identity_id == actor.id:
                raise DomainError(
                    "SELF_APPROVAL_PROHIBITED", "The Chairman cannot confirm their own requisition."
                )
        else:
            approver = (
                await officeholder(s, req.entity_id, route.authority.label, req.department_id)
            ).identity_id
            if approver == actor.id:
                raise DomainError(
                    "SELF_APPROVAL_PROHIBITED", "You cannot approve your own requisition."
                )
        route_data = {
            "authority": route.authority.label,
            "approver_id": str(approver) if approver else None,
            "policy_version": route.policy_version,
            "explanation": route.explanation,
            "requester_offices": sorted(offices),
            "requester_appointment_ids": sorted(str(o.id) for o in appointments),
            "secretary_id": str(secretary.identity_id)
            if route.authority.label == "board"
            else None,
            "chairman_id": str(chairman.identity_id) if route.authority.label == "board" else None,
        }
    else:
        if req.state != "PENDING_AUTHORITY" or not req.current_revision_id:
            raise DomainError(
                "INVALID_STATE_TRANSITION", "This request is not awaiting an individual decision."
            )
        revision = await s.get(Revision, req.current_revision_id)
        assert revision
        requester_name = revision.requester_name
        current = await officeholder(s, req.entity_id, revision.authority, req.department_id)
        if req.requester_id == actor.id:
            raise DomainError(
                "SELF_APPROVAL_PROHIBITED", "You cannot approve your own requisition."
            )
        if revision.approver_id != actor.id or current.identity_id != actor.id:
            raise DomainError(
                "ACCESS_DENIED", "Only the assigned current officeholder may decide.", 403
            )
        if intent.action in {"reject", "return"} and not intent.reason.strip():
            raise DomainError(
                "VALIDATION_FAILED", "Explain why you are rejecting or returning this request.", 422
            )
        route_data = {
            "authority": revision.authority,
            "approver_id": str(revision.approver_id),
            "appointment_id": str(current.id),
            "policy_version": revision.policy_version,
            "explanation": revision.routing_explanation,
        }
    entity = await s.get(Entity, req.entity_id)
    department = await s.get(Department, req.department_id)
    assert entity and department
    return {
        "entity_name": entity.name,
        "department_name": department.name,
        "entity_id": str(req.entity_id),
        "department_id": str(req.department_id),
        "request_id": str(req.id),
        "version": req.version,
        "revision_id": str(req.current_revision_id),
        "actor_id": str(actor.id),
        "action": intent.action,
        "reason": intent.reason,
        "content": req.content,
        "total": format(req.total, ".2f"),
        "route": route_data,
        "requester_name": requester_name,
        "context": req.context,
        "attachments": await attachment_manifest(s, req),
        "declaration": DECLARATION if intent.action == "submit" else intent.action,
        "declaration_version": DECLARATION_VERSION if intent.action == "submit" else "decision-v1",
    }


async def present(s: AsyncSession, req: Requisition, actor: Actor) -> RequestView:
    revision = await s.get(Revision, req.current_revision_id) if req.current_revision_id else None
    requester = await s.get(Identity, req.requester_id)
    entity = await s.get(Entity, req.entity_id)
    department = await s.get(Department, req.department_id)
    assert requester and entity and department
    actions = []
    blocker = None
    authority = revision.authority if revision else None
    explanation = revision.routing_explanation if revision else None
    decision_blocker = None
    if req.requester_id == actor.id and req.state == "DRAFT":
        try:
            await require_action(s, req, actor, "edit")
            actions = ["edit", "submit"]
            route = resolve(
                total_for(Content.model_validate(req.content)),
                {
                    o.role
                    for o in await active_offices(s, req.entity_id)
                    if o.identity_id == actor.id
                },
            )
            authority, explanation = route.authority.label, route.explanation
            await authorise_intent(
                s, req, actor, Intent(expected_version=req.version, action="submit")
            )
        except (DomainError, ValueError) as exc:
            blocker = exc.message if isinstance(exc, DomainError) else str(exc)
    if req.requester_id == actor.id and req.state == "RETURNED_FOR_REVISION":
        try:
            await require_action(s, req, actor, "revise")
            actions = ["revise"]
        except DomainError as exc:
            decision_blocker = exc.message
    if req.state == "PENDING_AUTHORITY" and revision:
        try:
            current = await officeholder(s, req.entity_id, revision.authority, req.department_id)
            if current.identity_id != revision.approver_id:
                raise DomainError(
                    "AUTHORITY_ASSIGNMENT_BLOCKED",
                    "The assigned approver no longer holds the required office. Contact your administrator.",
                )
            if revision.approver_id == actor.id:
                await require_action(s, req, actor, "approve")
                actions = ["approve", "reject", "return"]
        except DomainError as exc:
            decision_blocker = exc.message
    if revision and revision.authority == "board":
        from app.board.service import board_access

        try:
            await board_access(s, req, actor)
            actions.append("board_workspace")
        except DomainError as exc:
            if exc.code != "RESOURCE_NOT_AVAILABLE":
                decision_blocker = exc.message
    from app.history.service import history_page, next_action

    history = await history_page(s, req, actor)
    pending = await next_action(s, req, revision)
    projected, redacted = project_content(req.content, actor)
    if (
        req.context.get("bank_details_state") == "restricted"
        and "vendor.bank_details" not in redacted
    ):
        redacted.append("vendor.bank_details")
    if actor.account.read_only:
        actions = []
    return RequestView(
        id=req.id,
        entity_id=req.entity_id,
        reference=req.reference,
        requester_name=revision.requester_name if revision else requester.display_name,
        entity_name=revision.entity_name if revision else entity.name,
        department_name=revision.department_name if revision else department.name,
        state=req.state,
        version=req.version,
        total=format(req.total, ".2f"),
        created_at=req.created_at.isoformat(),
        required_authority=authority,
        routing_explanation=explanation,
        submission_blocker=blocker,
        decision_blocker=decision_blocker,
        content=Content.model_validate(projected),
        redacted_fields=redacted,
        available_actions=actions,
        revision_number=req.revision_number,
        history=[entry.model_dump(mode="json", exclude_none=True) for entry in history.items],
        next_action=pending,
    )


async def select_vendor(
    s: AsyncSession, actor: Actor, entity_id: UUID, body: CreateRequest | UpdateRequest
) -> dict[str, object]:
    if not body.vendor_selection:
        return {}
    vendor = await scoped_vendor(s, body.vendor_selection.id, actor)
    if vendor.entity_id != entity_id:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Vendor not found in this company.", 404)
    if vendor.version != body.vendor_selection.expected_version:
        raise DomainError("REVISION_CONFLICT", "Vendor details changed. Select the vendor again.")
    version = await s.get(VendorVersion, vendor.current_version_id)
    assert version
    snapshot = await vendor_view(s, vendor, version, actor)
    data = snapshot.data
    bank = data.bank
    body.content.vendor = VendorInfo(
        name=data.name,
        contact_person=data.contact_person,
        phone=", ".join(data.phones),
        email=str(data.email or ""),
        address=data.address,
        registration_id=data.registration_id,
        bank_name=bank.bank_name if bank else "",
        account_number=bank.account_number if bank else "",
        account_name=bank.account_name if bank else "",
    )
    return {
        "vendor_id": str(vendor.id),
        "vendor_version_id": str(version.id),
        "beneficiary_version_id": str(snapshot.beneficiary_version_id)
        if snapshot.beneficiary_version_id
        else None,
        "bank_details_state": snapshot.bank_details_state,
    }


async def attachment_manifest(s: AsyncSession, req: Requisition) -> list[dict[str, object]]:
    files = (
        await s.scalars(
            select(Attachment)
            .where(
                Attachment.requisition_id == req.id,
                Attachment.kind == "request_support",
                Attachment.detached.is_(False),
                Attachment.id.not_in([UUID(x) for x in req.excluded_attachment_ids]),
            )
            .order_by(Attachment.id)
        )
    ).all()
    if any(f.validation_state != "validated" for f in files):
        raise DomainError("VALIDATION_FAILED", "Remove invalid documents before submitting.", 422)
    return [
        {
            "id": str(f.id),
            "digest": f.digest,
            "object_version": f.object_version,
            "storage_key": f.storage_key,
            "filename": f.filename,
            "media_type": f.media_type,
            "byte_size": f.byte_size,
            "malware_scan": "not_performed",
        }
        for f in files
    ]


async def get_revision(s: AsyncSession, req: Requisition, number: int) -> Revision:
    revision = await s.scalar(
        select(Revision).where(Revision.requisition_id == req.id, Revision.number == number)
    )
    if not revision:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Submitted revision not found.", 404)
    return revision


async def revision_view(
    s: AsyncSession, req: Requisition, actor: Actor, number: int
) -> RequestView:
    revision = await get_revision(s, req, number)
    result = await present(s, req, actor)
    projected, redacted = project_content(revision.content, actor)
    decision = await s.scalar(select(Decision).where(Decision.revision_id == revision.id))
    state = {"approve": "APPROVED", "reject": "REJECTED", "return": "RETURNED_FOR_REVISION"}.get(
        decision.action if decision else "",
        "AWAITING_BOARD_RESOLUTION" if revision.authority == "board" else "PENDING_AUTHORITY",
    )
    if revision.authority == "board" and revision.id == req.current_revision_id:
        state = req.state
    context = revision.context.get("context", {})
    if (
        isinstance(context, dict)
        and context.get("bank_details_state") == "restricted"
        and "vendor.bank_details" not in redacted
    ):
        redacted.append("vendor.bank_details")
    return result.model_copy(
        update={
            "content": Content.model_validate(projected),
            "total": format(revision.total, ".2f"),
            "requester_name": revision.requester_name,
            "entity_name": revision.entity_name,
            "department_name": revision.department_name,
            "required_authority": revision.authority,
            "routing_explanation": revision.routing_explanation,
            "available_actions": [],
            "submission_blocker": None,
            "decision_blocker": None,
            "viewing_revision": number,
            "next_action": None,
            "revision_number": number,
            "state": state,
            "redacted_fields": redacted,
        }
    )
