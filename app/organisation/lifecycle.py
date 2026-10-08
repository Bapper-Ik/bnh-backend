import hashlib
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_event
from app.core.database import Identity, get_session
from app.core.errors import DomainError
from app.identity.models import Account
from app.identity.recovery import revoke_sessions
from app.identity.schemas import Command
from app.identity.service import Actor, current_actor, require_permission
from app.organisation.models import Department, Entity, Membership

router = APIRouter(prefix="/api/v1/organisation", tags=["Organisation"])


class DirectoryUpdate(Command):
    expected_version: str | None = Field(default=None, min_length=64, max_length=64)
    name: str | None = Field(default=None, min_length=2, max_length=180)
    active: bool | None = None


class DirectoryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    code: str
    active: bool


class StaffView(BaseModel):
    id: UUID
    name: str
    email: str
    active: bool


class MembershipState(Command):
    active: bool


def directory_version(record: Entity | Department) -> str:
    values = [str(record.id), record.name, record.code, str(record.active)]
    values.append(record.kind if isinstance(record, Entity) else str(record.entity_id))
    return hashlib.sha256("\0".join(values).encode()).hexdigest()


def check_version(record: Entity | Department, expected: str | None) -> None:
    if expected is not None and expected != directory_version(record):
        raise DomainError("REVISION_CONFLICT", "This record changed. Reload it before saving.", 409)


def apply_update(record: Entity | Department | Identity, body: DirectoryUpdate) -> None:
    if body.name is not None:
        if len(body.name.strip()) < 2:
            raise DomainError("VALIDATION_FAILED", "Supply a meaningful name.", 422)
        if isinstance(record, Identity):
            record.display_name = body.name.strip()
        else:
            record.name = body.name.strip()
    if body.active is not None and not isinstance(record, Identity):
        record.active = body.active


@router.patch("/entities/{entity_id}", response_model=DirectoryView)
async def update_entity(
    entity_id: UUID,
    body: DirectoryUpdate,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> DirectoryView:
    require_permission(actor, "organisation:manage")
    await s.execute(text("SELECT pg_advisory_xact_lock(67200602)"))
    entity = await s.scalar(select(Entity).where(Entity.id == entity_id).with_for_update())
    if not entity:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Company not found.", 404)
    check_version(entity, body.expected_version)
    if body.name is not None and await s.scalar(
        select(Entity.id).where(Entity.id != entity_id, Entity.name == body.name.strip())
    ):
        raise DomainError("VALIDATION_FAILED", "Company name already exists.", 422)
    apply_update(entity, body)
    await record_event(
        s,
        action="organisation.updated",
        actor_id=actor.id,
        resource_id=entity.id,
        entity_id=entity.id,
    )
    return DirectoryView.model_validate(entity)


@router.patch("/departments/{department_id}", response_model=DirectoryView)
async def update_department(
    department_id: UUID,
    body: DirectoryUpdate,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> DirectoryView:
    require_permission(actor, "organisation:manage")
    scope = await s.scalar(select(Department.entity_id).where(Department.id == department_id))
    if not scope:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Department not found.", 404)
    await s.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"), {"scope": str(scope)}
    )
    entity = await s.scalar(select(Entity).where(Entity.id == scope).with_for_update(read=True))
    department = await s.scalar(
        select(Department).where(Department.id == department_id).with_for_update()
    )
    if not department:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Department not found.", 404)
    check_version(department, body.expected_version)
    if body.active is True and (not entity or not entity.active):
        raise DomainError("VALIDATION_FAILED", "Enable the company before this department.", 422)
    if body.name is not None and await s.scalar(
        select(Department.id).where(
            Department.id != department_id,
            Department.entity_id == scope,
            Department.name == body.name.strip(),
        )
    ):
        raise DomainError(
            "VALIDATION_FAILED", "Department name already exists in this company.", 422
        )
    apply_update(department, body)
    await record_event(
        s,
        action="organisation.updated",
        actor_id=actor.id,
        resource_id=department.id,
        entity_id=department.entity_id,
    )
    return DirectoryView.model_validate(department)


@router.patch("/staff/{identity_id}", response_model=StaffView)
async def update_staff(
    identity_id: UUID,
    body: DirectoryUpdate,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> StaffView:
    require_permission(actor, "staff:manage")
    account = await s.scalar(
        select(Account).where(Account.identity_id == identity_id).with_for_update()
    )
    identity = await s.get(Identity, identity_id)
    if not account or not identity:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Staff member not found.", 404)
    if body.active is not None and identity_id == actor.id:
        raise DomainError(
            "ACCESS_DENIED", "Another administrator must change your account status.", 403
        )
    apply_update(identity, body)
    identity.version += 1
    if body.active is not None:
        account.active = body.active
        if not body.active:
            await revoke_sessions(s, account, actor.id)
    await record_event(s, action="identity.updated", actor_id=actor.id, resource_id=identity.id)
    return StaffView(
        id=identity.id, name=identity.display_name, email=account.email, active=account.active
    )


@router.patch("/memberships/{identity_id}/{entity_id}", response_model=MembershipState)
async def update_membership(
    identity_id: UUID,
    entity_id: UUID,
    body: MembershipState,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> MembershipState:
    require_permission(actor, "organisation:manage")
    if identity_id == actor.id:
        raise DomainError(
            "ACCESS_DENIED", "An operator cannot change their own organisational assignment.", 403
        )
    account = await s.scalar(
        select(Account).where(Account.identity_id == identity_id).with_for_update()
    )
    member = await s.scalar(
        select(Membership)
        .where(Membership.identity_id == identity_id, Membership.entity_id == entity_id)
        .with_for_update()
    )
    if not member:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Membership not found.", 404)
    if body.active:
        entity, department = (
            await s.get(Entity, entity_id),
            await s.get(Department, member.department_id),
        )
        if (
            not account
            or not account.active
            or not entity
            or not entity.active
            or not department
            or not department.active
        ):
            raise DomainError(
                "VALIDATION_FAILED",
                "Restore the staff, company and department before membership.",
                422,
            )
    member.active = body.active
    await record_event(
        s,
        action="identity.updated",
        actor_id=actor.id,
        resource_id=identity_id,
        entity_id=entity_id,
    )
    return body
