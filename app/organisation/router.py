from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.audit.service import AuditDetails, record_event
from app.core.database import Identity, get_session
from app.core.errors import DomainError
from app.identity.models import Account
from app.identity.schemas import Command
from app.identity.service import Actor, current_actor, hasher, require_permission
from app.organisation.models import Department, Entity, Membership, Office

router = APIRouter(prefix="/api/v1/organisation", tags=["Organisation"])


class DirectoryInput(Command):
    name: str = Field(min_length=2, max_length=180)
    code: str = Field(
        default_factory=lambda: uuid4().hex[:16],
        min_length=2,
        max_length=40,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    @model_validator(mode="after")
    def meaningful_name(self) -> "DirectoryInput":
        self.name = self.name.strip()
        if len(self.name) < 2:
            raise ValueError("Supply a meaningful name")
        return self


class EntityInput(DirectoryInput):
    kind: Literal["holding", "subsidiary"] = "subsidiary"


class DepartmentInput(DirectoryInput):
    entity_id: UUID


class StaffInput(Command):
    name: str = Field(min_length=2, max_length=180)
    email: EmailStr
    initial_password: str = Field(min_length=12, max_length=1024)


class MembershipInput(Command):
    identity_id: UUID
    entity_id: UUID
    department_id: UUID


class OfficeInput(Command):
    identity_id: UUID
    entity_id: UUID
    department_id: UUID | None = None
    role: Literal["hod", "chief_of_staff", "md", "secretary", "chairman"]
    authorisation_reference: str = Field(min_length=3, max_length=300)
    valid_from: datetime = Field(default_factory=lambda: datetime.now(UTC))
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def valid_dates(self) -> "OfficeInput":
        if self.valid_from.tzinfo is None or (
            self.valid_until is not None and self.valid_until.tzinfo is None
        ):
            raise ValueError("Appointment dates require a timezone")
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("Appointment end must follow its start")
        if not self.authorisation_reference.strip():
            raise ValueError("An authorisation reference is required")
        return self


class Item(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    code: str
    active: bool


class EntityItem(Item):
    kind: str


class StaffItem(BaseModel):
    id: UUID
    name: str
    email: str
    active: bool


class MembershipView(BaseModel):
    entity_id: UUID
    entity_name: str
    department_id: UUID
    department_name: str


class OfficeView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    identity_id: UUID
    entity_id: UUID
    department_id: UUID | None
    role: str
    active: bool
    valid_from: datetime
    valid_until: datetime | None
    authorisation_reference: str


@router.get("/memberships", response_model=list[MembershipView])
async def my_memberships(
    actor: Actor = Depends(current_actor), s: AsyncSession = Depends(get_session, scope="function")
) -> list[MembershipView]:
    rows = (
        await s.execute(
            select(Membership, Entity, Department)
            .join(Entity, Entity.id == Membership.entity_id)
            .join(Department, Department.id == Membership.department_id)
            .where(
                Membership.identity_id == actor.id,
                Membership.active.is_(True),
                Entity.active.is_(True),
                Department.active.is_(True),
            )
        )
    ).all()
    return [
        MembershipView(
            entity_id=m.entity_id,
            entity_name=e.name,
            department_id=m.department_id,
            department_name=d.name,
        )
        for m, e, d in rows
    ]


@router.get("/entities", response_model=list[EntityItem])
async def entities(
    actor: Actor = Depends(current_actor), s: AsyncSession = Depends(get_session, scope="function")
) -> list[EntityItem]:
    require_permission(actor, "organisation:manage")
    return [
        EntityItem.model_validate(e)
        for e in (await s.scalars(select(Entity).order_by(Entity.name))).all()
    ]


@router.post("/entities", response_model=EntityItem, status_code=201)
async def create_entity(
    body: EntityInput,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> Item:
    require_permission(actor, "organisation:manage")
    await s.execute(text("SELECT pg_advisory_xact_lock(67200602)"))
    if await s.scalar(
        select(Entity.id).where(or_(Entity.name == body.name, Entity.code == body.code))
    ):
        raise DomainError("VALIDATION_FAILED", "Company name or code already exists.", 422)
    entity = Entity(name=body.name, code=body.code, kind=body.kind)
    s.add(entity)
    await s.flush()
    await record_event(
        s,
        action="organisation.created",
        actor_id=actor.id,
        resource_id=entity.id,
        entity_id=entity.id,
    )
    return EntityItem.model_validate(entity)


@router.get("/departments", response_model=list[Item])
async def departments(
    entity_id: UUID,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> list[Item]:
    require_permission(actor, "organisation:manage")
    return [
        Item.model_validate(d)
        for d in (
            await s.scalars(select(Department).where(Department.entity_id == entity_id))
        ).all()
    ]


@router.post("/departments", response_model=Item, status_code=201)
async def create_department(
    body: DepartmentInput,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> Item:
    require_permission(actor, "organisation:manage")
    await s.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
        {"scope": str(body.entity_id)},
    )
    entity = await s.scalar(
        select(Entity).where(Entity.id == body.entity_id).with_for_update(read=True)
    )
    if not entity or not entity.active:
        raise DomainError("VALIDATION_FAILED", "Select an active company.", 422)
    if await s.scalar(
        select(Department.id).where(
            Department.entity_id == body.entity_id,
            or_(Department.name == body.name, Department.code == body.code),
        )
    ):
        raise DomainError("VALIDATION_FAILED", "Department name or code already exists.", 422)
    department = Department(entity_id=body.entity_id, name=body.name, code=body.code)
    s.add(department)
    await s.flush()
    await record_event(
        s,
        action="organisation.created",
        actor_id=actor.id,
        resource_id=department.id,
        entity_id=body.entity_id,
    )
    return Item.model_validate(department)


@router.get("/staff", response_model=list[StaffItem])
async def staff(
    actor: Actor = Depends(current_actor), s: AsyncSession = Depends(get_session, scope="function")
) -> list[StaffItem]:
    require_permission(actor, "staff:manage")
    rows = (
        await s.execute(
            select(Identity, Account)
            .join(Account, Account.identity_id == Identity.id)
            .order_by(Identity.display_name)
            .limit(200)
        )
    ).all()
    return [
        StaffItem(id=i.id, name=i.display_name, email=a.email, active=a.active) for i, a in rows
    ]


@router.post("/staff", response_model=StaffItem, status_code=201)
async def create_staff(
    body: StaffInput,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> StaffItem:
    require_permission(actor, "staff:manage")
    if await s.scalar(select(Account.id).where(Account.email == str(body.email).lower())):
        raise DomainError("VALIDATION_FAILED", "An account already uses that email.", 422)
    if len(body.name.strip()) < 2:
        raise DomainError("VALIDATION_FAILED", "Supply the staff member's full name.", 422)
    identity = Identity(display_name=body.name.strip())
    s.add(identity)
    await s.flush()
    account = Account(
        identity_id=identity.id,
        email=str(body.email).lower(),
        password_hash=await run_in_threadpool(hasher.hash, body.initial_password),
        permissions=[],
    )
    s.add(account)
    await record_event(s, action="identity.created", actor_id=actor.id, resource_id=identity.id)
    return StaffItem(id=identity.id, name=identity.display_name, email=account.email, active=True)


@router.post("/memberships", response_model=MembershipInput, status_code=201)
async def create_membership(
    body: MembershipInput,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> MembershipInput:
    require_permission(actor, "organisation:manage")
    if body.identity_id == actor.id:
        raise DomainError(
            "ACCESS_DENIED", "An operator cannot change their own organisational assignment.", 403
        )
    account = await s.scalar(
        select(Account).where(Account.identity_id == body.identity_id).with_for_update()
    )
    department = await s.get(Department, body.department_id)
    entity = await s.get(Entity, body.entity_id)
    if (
        not account
        or not account.active
        or not entity
        or not entity.active
        or not department
        or not department.active
        or department.entity_id != body.entity_id
    ):
        raise DomainError(
            "VALIDATION_FAILED", "Select active matching staff, company and department.", 422
        )
    stored = await s.scalar(
        select(Membership)
        .where(Membership.identity_id == body.identity_id, Membership.entity_id == body.entity_id)
        .with_for_update()
    )
    if stored:
        if stored.department_id != body.department_id:
            held_hod = await s.scalar(
                select(Office.id).where(
                    Office.identity_id == body.identity_id,
                    Office.entity_id == body.entity_id,
                    Office.role == "hod",
                    Office.active.is_(True),
                )
            )
            if held_hod:
                raise DomainError(
                    "AUTHORITY_ASSIGNMENT_BLOCKED",
                    "Revoke the current HOD appointment before transferring its holder.",
                )
        stored.department_id, stored.active = body.department_id, True
    else:
        s.add(Membership(**body.model_dump()))
    await record_event(
        s,
        action="identity.updated",
        actor_id=actor.id,
        resource_id=body.identity_id,
        entity_id=body.entity_id,
    )
    return body


@router.get("/offices", response_model=list[OfficeView])
async def offices(
    entity_id: UUID,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> list[OfficeView]:
    require_permission(actor, "office_assignment:manage")
    records = (
        await s.scalars(
            select(Office).where(Office.entity_id == entity_id).order_by(Office.created_at.desc())
        )
    ).all()
    return [OfficeView.model_validate(o) for o in records]


@router.post("/offices", response_model=OfficeView, status_code=201)
async def assign_office(
    body: OfficeInput,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> OfficeView:
    require_permission(actor, "office_assignment:manage")
    if body.identity_id == actor.id:
        raise DomainError("ACCESS_DENIED", "You cannot grant yourself an office.", 403)
    await s.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
        {"scope": str(body.entity_id)},
    )
    entity = await s.get(Entity, body.entity_id)
    account = await s.scalar(
        select(Account).where(Account.identity_id == body.identity_id).with_for_update()
    )
    if (
        not entity
        or not entity.active
        or not account
        or not account.active
        or account.password_pending
        or account.read_only
    ):
        raise DomainError("VALIDATION_FAILED", "Select active staff and company.", 422)
    member = await s.scalar(
        select(Membership).where(
            Membership.identity_id == body.identity_id,
            Membership.entity_id == body.entity_id,
            Membership.active.is_(True),
        )
    )
    member_department = await s.get(Department, member.department_id) if member else None
    if not member or not member_department or not member_department.active:
        raise DomainError(
            "VALIDATION_FAILED", "The officeholder needs active membership in this company.", 422
        )
    if body.role == "hod":
        department = await s.get(Department, body.department_id) if body.department_id else None
        if (
            not department
            or not department.active
            or department.entity_id != body.entity_id
            or member.department_id != department.id
        ):
            raise DomainError(
                "VALIDATION_FAILED", "HOD appointment requires a department in this company.", 422
            )
    elif body.department_id:
        raise DomainError(
            "VALIDATION_FAILED", "Executive and Board offices are company-scoped.", 422
        )
    existing = [
        o
        for o in (
            await s.scalars(
                select(Office).where(Office.entity_id == body.entity_id, Office.active.is_(True))
            )
        ).all()
        if o.role == body.role and o.department_id == body.department_id
    ]
    if existing:
        raise DomainError(
            "AUTHORITY_ASSIGNMENT_BLOCKED",
            "Revoke the existing appointment before appointing its replacement.",
        )
    if body.role in {"secretary", "chairman"}:
        conflict = await s.scalar(
            select(Office.id).where(
                Office.entity_id == body.entity_id,
                Office.identity_id == body.identity_id,
                Office.active.is_(True),
                Office.role.in_(["secretary", "chairman"]),
            )
        )
        if conflict:
            raise DomainError(
                "AUTHORITY_ASSIGNMENT_BLOCKED", "Secretary and Chairman must be different people."
            )
    office = Office(**body.model_dump())
    s.add(office)
    await s.flush()
    await record_event(
        s,
        action="office.assigned",
        actor_id=actor.id,
        resource_id=office.id,
        entity_id=body.entity_id,
        details=AuditDetails(office=body.role, department_id=body.department_id),
    )
    return OfficeView.model_validate(office)


@router.post("/offices/{office_id}/revoke", response_model=OfficeView)
async def revoke(
    office_id: UUID,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> OfficeView:
    require_permission(actor, "office_assignment:manage")
    holder = await s.scalar(select(Office.identity_id).where(Office.id == office_id))
    if holder:
        await s.scalar(select(Account).where(Account.identity_id == holder).with_for_update())
    office = await s.scalar(select(Office).where(Office.id == office_id).with_for_update())
    if not office:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Appointment not found.", 404)
    if not office.active:
        return OfficeView.model_validate(office)
    office.active = False
    await record_event(
        s,
        action="office.revoked",
        actor_id=actor.id,
        resource_id=office.id,
        entity_id=office.entity_id,
    )
    return OfficeView.model_validate(office)
