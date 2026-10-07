"""Screen 11: controlled staff directory and versioned account administration."""

import hashlib
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_event
from app.core.database import Identity, get_session
from app.core.errors import DomainError
from app.identity.email_delivery import queue_link
from app.identity.models import Account, RecoveryToken
from app.identity.recovery import revoke_sessions
from app.identity.schemas import Command
from app.identity.service import Actor, current_actor, require_permission
from app.organisation.lifecycle import (
    DirectoryUpdate,
    MembershipState,
    update_membership,
    update_staff,
)
from app.organisation.models import Department, Entity, Membership, Office
from app.organisation.router import (
    MembershipInput,
    OfficeInput,
    OfficeView,
    assign_office,
    create_membership,
    revoke,
)

router = APIRouter(prefix="/api/v1/staff", tags=["Staff management"])
Status = Literal["active", "invited", "disabled"]


class StaffSummary(BaseModel):
    id: UUID
    name: str
    email: str
    status: Status
    read_only: bool


class StaffPage(BaseModel):
    items: list[StaffSummary]
    total: int
    limit: int
    offset: int


class StaffMembership(BaseModel):
    entity_id: UUID
    entity_name: str
    department_id: UUID
    department_name: str
    active: bool
    scope_active: bool


class StaffDetail(StaffSummary):
    version: str
    memberships: list[StaffMembership]
    offices: list[OfficeView]
    actions: list[str]


class StaffOption(BaseModel):
    id: UUID
    name: str
    entity_id: UUID | None = None


class StaffOptions(BaseModel):
    entities: list[StaffOption]
    departments: list[StaffOption]
    email_enabled: bool


class StaffVersion(Command):
    expected_version: str = Field(min_length=64, max_length=64)


class StaffEdit(StaffVersion):
    name: str = Field(min_length=2, max_length=180)


class StaffState(StaffVersion):
    active: bool


class StaffMembershipSet(MembershipInput, StaffVersion):
    pass


class StaffMembershipState(StaffVersion):
    active: bool


class StaffOfficeSet(OfficeInput, StaffVersion):
    pass


def summary(identity: Identity, account: Account) -> StaffSummary:
    return StaffSummary(
        id=identity.id,
        name=identity.display_name,
        email=account.email,
        status="disabled"
        if not account.active
        else "invited"
        if account.password_pending
        else "active",
        read_only=account.read_only,
    )


async def detail(s: AsyncSession, identity_id: UUID, actor: Actor) -> StaffDetail:
    row = (
        await s.execute(
            select(Identity, Account)
            .join(Account, Account.identity_id == Identity.id)
            .where(Identity.id == identity_id)
        )
    ).one_or_none()
    if not row:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Staff member not found.", 404)
    identity, account = row
    memberships = [
        StaffMembership(
            entity_id=m.entity_id,
            entity_name=e.name,
            department_id=m.department_id,
            department_name=d.name,
            active=m.active,
            scope_active=e.active and d.active,
        )
        for m, e, d in (
            await s.execute(
                select(Membership, Entity, Department)
                .join(Entity, Entity.id == Membership.entity_id)
                .join(Department, Department.id == Membership.department_id)
                .where(Membership.identity_id == identity_id)
                .order_by(Membership.entity_id)
            )
        ).all()
    ]
    offices = [
        OfficeView.model_validate(o)
        for o in (
            await s.scalars(
                select(Office).where(Office.identity_id == identity_id).order_by(Office.id)
            )
        ).all()
    ]
    latest_link = await s.scalar(
        select(RecoveryToken.id)
        .where(RecoveryToken.account_id == account.id)
        .order_by(RecoveryToken.created_at.desc(), RecoveryToken.id)
        .limit(1)
    )
    projection = StaffDetail(
        **summary(identity, account).model_dump(),
        version="",
        memberships=memberships,
        offices=offices,
        actions=[],
    )
    # Hash only server projections. It covers activation, legacy API changes and
    # appointments without adding a parallel writable version to those records.
    projection.version = hashlib.sha256(
        (projection.model_dump_json() + str(identity.version) + str(latest_link)).encode()
    ).hexdigest()
    actions = ["edit"]
    if identity_id != actor.id:
        actions += ["disable" if account.active else "enable", "revoke_sessions"]
        if account.active and account.password_pending:
            actions.append("resend_invitation")
        if "organisation:manage" in actor.account.permissions:
            actions.append("set_membership")
        if "office_assignment:manage" in actor.account.permissions:
            actions.append("revoke_office")
            if account.active and not account.password_pending and not account.read_only:
                actions.append("assign_office")
    projection.actions = actions
    return projection


async def locked(s: AsyncSession, identity_id: UUID, actor: Actor, version: str) -> Account:
    require_permission(actor, "staff:manage")
    account = await s.scalar(
        select(Account).where(Account.identity_id == identity_id).with_for_update()
    )
    if not account:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Staff member not found.", 404)
    current = await detail(s, identity_id, actor)
    if current.version != version:
        raise DomainError(
            "REVISION_CONFLICT", "This staff record changed. Reload it before saving.", 409
        )
    return account


@router.get("", response_model=StaffPage)
async def directory(
    search: str = Query(default="", max_length=180),
    status: Status | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> StaffPage:
    require_permission(actor, "staff:manage")
    query = select(Identity, Account).join(Account, Account.identity_id == Identity.id)
    if search.strip():
        escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(
            or_(
                Identity.display_name.ilike(f"%{escaped}%", escape="\\"),
                Account.email.ilike(f"%{escaped}%", escape="\\"),
            )
        )
    if status == "disabled":
        query = query.where(Account.active.is_(False))
    elif status:
        query = query.where(
            Account.active.is_(True), Account.password_pending.is_(status == "invited")
        )
    total = await s.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await s.execute(
            query.order_by(func.lower(Identity.display_name), Identity.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return StaffPage(
        items=[summary(i, a) for i, a in rows], total=total or 0, limit=limit, offset=offset
    )


@router.get("/options", response_model=StaffOptions)
async def options(
    request: Request,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> StaffOptions:
    require_permission(actor, "staff:manage")
    entities, departments = [], []
    if {"organisation:manage", "office_assignment:manage"} & set(actor.account.permissions):
        entities = [
            StaffOption(id=e.id, name=e.name)
            for e in (
                await s.scalars(select(Entity).where(Entity.active.is_(True)).order_by(Entity.name))
            ).all()
        ]
        departments = [
            StaffOption(id=d.id, name=d.name, entity_id=d.entity_id)
            for d in (
                await s.scalars(
                    select(Department)
                    .join(Entity)
                    .where(Department.active.is_(True), Entity.active.is_(True))
                    .order_by(Department.name)
                )
            ).all()
        ]
    return StaffOptions(
        entities=entities,
        departments=departments,
        email_enabled=request.app.state.settings.mail_enabled,
    )


@router.get("/{identity_id}", response_model=StaffDetail)
async def staff_detail(
    identity_id: UUID,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> StaffDetail:
    require_permission(actor, "staff:manage")
    return await detail(s, identity_id, actor)


@router.patch("/{identity_id}", response_model=StaffDetail)
async def edit(
    identity_id: UUID,
    body: StaffEdit,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> StaffDetail:
    await locked(s, identity_id, actor, body.expected_version)
    await update_staff(identity_id, DirectoryUpdate(name=body.name), actor, s)
    await s.flush()
    return await detail(s, identity_id, actor)


@router.post("/{identity_id}/state", response_model=StaffDetail)
async def state(
    identity_id: UUID,
    body: StaffState,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> StaffDetail:
    await locked(s, identity_id, actor, body.expected_version)
    await update_staff(identity_id, DirectoryUpdate(active=body.active), actor, s)
    await s.flush()
    return await detail(s, identity_id, actor)


@router.post("/{identity_id}/revoke-sessions", response_model=StaffDetail)
async def end_sessions(
    identity_id: UUID,
    body: StaffVersion,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> StaffDetail:
    account = await locked(s, identity_id, actor, body.expected_version)
    if identity_id == actor.id:
        raise DomainError(
            "ACCESS_DENIED", "Use your own account security controls to end your sessions.", 403
        )
    await revoke_sessions(s, account, actor.id)
    return await detail(s, identity_id, actor)


@router.post("/{identity_id}/invitation", response_model=StaffDetail)
async def resend(
    identity_id: UUID,
    body: StaffVersion,
    request: Request,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> StaffDetail:
    account = await locked(s, identity_id, actor, body.expected_version)
    if not account.active or not account.password_pending:
        raise DomainError(
            "INVITATION_CONFLICT", "Only an enabled pending account can be invited.", 409
        )
    await queue_link(s, account, request.app.state.settings)
    await record_event(s, action="auth.invited", actor_id=actor.id, resource_id=identity_id)
    await s.flush()
    return await detail(s, identity_id, actor)


@router.post("/{identity_id}/memberships", response_model=StaffDetail)
async def membership(
    identity_id: UUID,
    body: StaffMembershipSet,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> StaffDetail:
    require_permission(actor, "organisation:manage")
    if body.identity_id != identity_id:
        raise DomainError("VALIDATION_FAILED", "Staff selection does not match this record.", 422)
    await locked(s, identity_id, actor, body.expected_version)
    await create_membership(
        MembershipInput(**body.model_dump(exclude={"expected_version"})), actor, s
    )
    await s.flush()
    return await detail(s, identity_id, actor)


@router.post("/{identity_id}/memberships/{entity_id}/state", response_model=StaffDetail)
async def membership_state(
    identity_id: UUID,
    entity_id: UUID,
    body: StaffMembershipState,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> StaffDetail:
    require_permission(actor, "organisation:manage")
    await locked(s, identity_id, actor, body.expected_version)
    await update_membership(identity_id, entity_id, MembershipState(active=body.active), actor, s)
    await s.flush()
    return await detail(s, identity_id, actor)


@router.post("/{identity_id}/offices", response_model=StaffDetail)
async def appointment(
    identity_id: UUID,
    body: StaffOfficeSet,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> StaffDetail:
    require_permission(actor, "staff:manage")
    require_permission(actor, "office_assignment:manage")
    if body.identity_id != identity_id:
        raise DomainError("VALIDATION_FAILED", "Staff selection does not match this record.", 422)
    # Match the existing office assignment lock order: entity scope then account.
    await s.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
        {"scope": str(body.entity_id)},
    )
    await locked(s, identity_id, actor, body.expected_version)
    await assign_office(OfficeInput(**body.model_dump(exclude={"expected_version"})), actor, s)
    await s.flush()
    return await detail(s, identity_id, actor)


@router.post("/{identity_id}/offices/{office_id}/revoke", response_model=StaffDetail)
async def revoke_appointment(
    identity_id: UUID,
    office_id: UUID,
    body: StaffVersion,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> StaffDetail:
    require_permission(actor, "office_assignment:manage")
    await locked(s, identity_id, actor, body.expected_version)
    office = await s.get(Office, office_id)
    if not office or office.identity_id != identity_id:
        raise DomainError(
            "RESOURCE_NOT_AVAILABLE", "Appointment not found for this staff member.", 404
        )
    if identity_id == actor.id:
        raise DomainError(
            "ACCESS_DENIED", "Another authorised operator must change your appointments.", 403
        )
    await revoke(office_id, actor, s)
    await s.flush()
    return await detail(s, identity_id, actor)
