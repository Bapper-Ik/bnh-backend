"""Organisation & Authority screen: directory versions and appointment visibility."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.database import Identity, get_session
from app.core.errors import DomainError
from app.identity.models import Account
from app.identity.service import Actor, current_actor, require_permission
from app.organisation.lifecycle import (
    DirectoryUpdate,
    directory_version,
    update_department,
    update_entity,
)
from app.organisation.models import Department, Entity, Membership, Office
from app.organisation.router import OfficeView

router = APIRouter(prefix="/api/v1/organisation/workspace", tags=["Organisation workspace"])


class OrganisationRecord(BaseModel):
    id: UUID
    name: str
    code: str
    active: bool
    version: str
    kind: str | None = None
    entity_id: UUID | None = None


class OrganisationEdit(DirectoryUpdate):
    expected_version: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def has_change(self) -> "OrganisationEdit":
        if self.name is None and self.active is None:
            raise ValueError("Supply a name or enabled state")
        return self


class NamedOffice(OfficeView):
    holder_name: str
    department_name: str | None
    status: Literal["active", "revoked", "expired", "scheduled", "blocked"]
    reason: str


class AuthorityRow(BaseModel):
    requester: str
    authorities: list[str]


class OrganisationWorkspace(BaseModel):
    entities: list[OrganisationRecord]
    selected_entity: UUID | None
    departments: list[OrganisationRecord]
    offices: list[NamedOffice]
    authority_gaps: list[str]
    bands: list[str]
    matrix: list[AuthorityRow]
    rules: list[str]


def record(value: Entity | Department) -> OrganisationRecord:
    return OrganisationRecord(
        id=value.id,
        name=value.name,
        code=value.code,
        active=value.active,
        version=directory_version(value),
        kind=value.kind if isinstance(value, Entity) else None,
        entity_id=value.entity_id if isinstance(value, Department) else None,
    )


async def appointment_views(s: AsyncSession, entity: Entity) -> list[NamedOffice]:
    member_department = aliased(Department)
    office_department = aliased(Department)
    rows = (
        await s.execute(
            select(
                Office,
                Identity.display_name,
                Account,
                Membership,
                member_department,
                office_department.name,
            )
            .join(Identity, Identity.id == Office.identity_id)
            .join(Account, Account.identity_id == Office.identity_id)
            .outerjoin(
                Membership,
                (Membership.identity_id == Office.identity_id)
                & (Membership.entity_id == Office.entity_id),
            )
            .outerjoin(member_department, member_department.id == Membership.department_id)
            .outerjoin(office_department, office_department.id == Office.department_id)
            .where(Office.entity_id == entity.id)
            .order_by(Office.created_at.desc(), Office.id)
        )
    ).all()
    now = datetime.now(UTC)
    result = []
    for office, name, account, member, department, department_name in rows:
        status: Literal["active", "revoked", "expired", "scheduled", "blocked"] = "active"
        reason = "Effective within this company; request-specific checks still apply."
        if not office.active:
            status, reason = "revoked", "Appointment revoked; retained for history."
        elif office.valid_until is not None and office.valid_until <= now:
            status, reason = "expired", "The appointment end date has passed."
        elif not entity.active:
            status, reason = "blocked", "Company disabled."
        elif not account.active or account.password_pending or account.read_only:
            status, reason = (
                "blocked",
                "Staff account is disabled, pending activation or read-only.",
            )
        elif not member or not member.active or not department or not department.active:
            status, reason = "blocked", "Active company and department membership required."
        elif office.role == "hod" and office.department_id != member.department_id:
            status, reason = "blocked", "HOD department does not match current membership."
        elif office.valid_from > now:
            status, reason = "scheduled", "The appointment has not started."
        result.append(
            NamedOffice(
                **OfficeView.model_validate(office).model_dump(),
                holder_name=name,
                department_name=department_name,
                status=status,
                reason=reason,
            )
        )
    return result


def authority_gaps(
    entity: Entity | None, departments: list[Department], offices: list[NamedOffice]
) -> list[str]:
    if not entity or not entity.active:
        return []
    scopes: list[tuple[str, UUID | None, str]] = [
        ("hod", d.id, f"Head of Department · {d.name}") for d in departments if d.active
    ]
    scopes += [
        (role, None, label)
        for role, label in (
            ("chief_of_staff", "Chief of Staff"),
            ("md", "Managing Director"),
            ("secretary", "Company Secretary"),
            ("chairman", "Board Chairman"),
        )
    ]
    gaps = []
    for role, department_id, label in scopes:
        candidates = [
            o
            for o in offices
            if o.status == "active" and o.role == role and o.department_id == department_id
        ]
        if not candidates:
            gaps.append(f"{label}: no currently effective appointment.")
        elif len(candidates) > 1:
            gaps.append(f"{label}: conflicting current appointments require correction.")
            for office in candidates:
                office.status = "blocked"
                office.reason = "Multiple current appointments conflict in this office scope."
    return gaps


@router.get("", response_model=OrganisationWorkspace)
async def workspace(
    entity_id: UUID | None = None,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> OrganisationWorkspace:
    require_permission(actor, "organisation:manage")
    entities = list((await s.scalars(select(Entity).order_by(Entity.name, Entity.id))).all())
    entity = (
        next((e for e in entities if e.id == entity_id), None)
        if entity_id
        else next(iter(entities), None)
    )
    if entity_id and not entity:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Company not found.", 404)
    departments = (
        list(
            (
                await s.scalars(
                    select(Department)
                    .where(Department.entity_id == entity.id)
                    .order_by(Department.name, Department.id)
                )
            ).all()
        )
        if entity
        else []
    )
    offices = await appointment_views(s, entity) if entity else []
    gaps = authority_gaps(entity, departments, offices)
    return OrganisationWorkspace(
        entities=[record(e) for e in entities],
        selected_entity=entity.id if entity else None,
        departments=[record(d) for d in departments],
        offices=offices,
        authority_gaps=gaps,
        bands=[
            "₦1–₦5,000,000",
            "Above ₦5,000,000–₦100,000,000",
            "Above ₦100,000,000–₦500,000,000",
            "Above ₦500,000,000",
        ],
        matrix=[
            AuthorityRow(
                requester="Ordinary staff",
                authorities=["Own department HOD", "Chief of Staff", "Managing Director", "Board"],
            ),
            AuthorityRow(
                requester="Head of Department",
                authorities=["Chief of Staff", "Chief of Staff", "Managing Director", "Board"],
            ),
            AuthorityRow(
                requester="Chief of Staff",
                authorities=[
                    "Managing Director",
                    "Managing Director",
                    "Managing Director",
                    "Board",
                ],
            ),
            AuthorityRow(
                requester="Managing Director", authorities=["Board", "Board", "Board", "Board"]
            ),
        ],
        rules=[
            "Upper limits are inclusive. Routing is direct to the higher of the amount requirement and requester office minimum.",
            "No self-approval or substitute authority through seniority. Missing or conflicting appointments block the affected action.",
            "Appointments apply only to their named company. A holding-company appointment does not automatically apply to subsidiaries.",
            "Board decisions require a meeting resolution recorded and signed by the Company Secretary, then confirmed and signed by a different Board Chairman who is also different from the requester.",
            "Board confirmation preserves the meeting outcome: approval, rejection, deferment or conditional approval. Unresolved conditions remain on hold.",
            "Approval authorises a requisition; it does not record or execute payment.",
        ],
    )


@router.patch("/entities/{entity_id}", response_model=OrganisationRecord)
async def edit_company(
    entity_id: UUID,
    body: OrganisationEdit,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> OrganisationRecord:
    await update_entity(entity_id, body, actor, s)
    await s.flush()
    value = await s.get(Entity, entity_id)
    assert value
    return record(value)


@router.patch("/departments/{department_id}", response_model=OrganisationRecord)
async def edit_department(
    department_id: UUID,
    body: OrganisationEdit,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> OrganisationRecord:
    await update_department(department_id, body, actor, s)
    await s.flush()
    value = await s.get(Department, department_id)
    assert value
    return record(value)
