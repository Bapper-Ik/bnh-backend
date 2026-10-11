from decimal import Decimal

from sqlalchemy import and_
from sqlalchemy.sql.elements import ColumnElement

from app.authority.policy import HOD_SELF_APPROVAL_POLICY
from app.requisitions.models import Requisition, Revision


def hod_self_approval(req: Requisition, revision: Revision) -> bool:
    """Only the expressly captured v2 exception; historical routes keep their policy."""
    route = revision.context.get("route", {})
    return (
        revision.policy_version == HOD_SELF_APPROVAL_POLICY
        and revision.authority == "hod"
        and Decimal("1") <= revision.total <= Decimal("5000000")
        and revision.approver_id == req.requester_id
        and isinstance(route, dict)
        and route.get("self_approval") is True
    )


def hod_self_approval_scope() -> ColumnElement[bool]:
    return and_(
        Revision.policy_version == HOD_SELF_APPROVAL_POLICY,
        Revision.authority == "hod",
        Revision.total.between(Decimal("1"), Decimal("5000000")),
        Revision.approver_id == Requisition.requester_id,
        Revision.context["route"]["self_approval"].as_boolean().is_(True),
    )
