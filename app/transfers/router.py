from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import AuditDetails, record_event
from app.core.database import get_session
from app.core.errors import DomainError
from app.identity.service import Actor, current_actor, require_permission
from app.organisation.models import Department, Entity
from app.transfers.models import CompanyDebitAccount, DepartmentDebitAccount
from app.transfers.schemas import DebitAccount, DebitAccountUpdate, DebitAccountView

router = APIRouter(prefix="/api/v1/organisation", tags=["Bank instructions"])


async def company(s: AsyncSession, actor: Actor, entity_id: UUID, lock: bool = False) -> Entity:
    require_permission(actor, "organisation:manage")
    query = select(Entity).where(Entity.id == entity_id)
    if lock:
        query = query.with_for_update()
    row = await s.scalar(query)
    if not row:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Company not found.", 404)
    return row


@router.get("/entities/{entity_id}/debit-account", response_model=DebitAccountView)
async def get_account(
    entity_id: UUID,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> DebitAccountView:
    await company(s, actor, entity_id)
    row = await s.get(CompanyDebitAccount, entity_id)
    return DebitAccountView(
        version=row.version if row else 0,
        data=DebitAccount.model_validate(row.data) if row else None,
    )


@router.put("/entities/{entity_id}/debit-account", response_model=DebitAccountView)
async def put_account(
    entity_id: UUID,
    body: DebitAccountUpdate,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> DebitAccountView:
    entity = await company(s, actor, entity_id, lock=True)
    if not entity.active:
        raise DomainError(
            "ACCESS_DENIED", "Enable this company before configuring its bank account.", 403
        )
    row = await s.get(CompanyDebitAccount, entity_id, populate_existing=True)
    if (row.version if row else 0) != body.expected_version:
        raise DomainError(
            "REVISION_CONFLICT", "The company bank details changed. Reload before saving."
        )
    if row:
        row.data = body.data.model_dump(mode="json")
        row.version += 1
    else:
        row = CompanyDebitAccount(
            entity_id=entity_id, version=1, data=body.data.model_dump(mode="json")
        )
        s.add(row)
    await record_event(
        s,
        action="organisation.debit_account.updated",
        actor_id=actor.id,
        resource_id=entity_id,
        entity_id=entity_id,
        details=AuditDetails(resource_type="organisation"),
    )
    return DebitAccountView(version=row.version, data=body.data)


async def department(
    s: AsyncSession, actor: Actor, department_id: UUID, lock: bool = False
) -> tuple[Department, Entity]:
    require_permission(actor, "organisation:manage")
    # Lock in the same company-then-department order as organisation maintenance.
    row = await s.get(Department, department_id)
    if not row:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Department not found.", 404)
    entity = await company(s, actor, row.entity_id, lock=lock)
    if lock:
        row = await s.scalar(
            select(Department)
            .where(Department.id == department_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert row
    return row, entity


@router.get("/departments/{department_id}/debit-account", response_model=DebitAccountView)
async def get_department_account(
    department_id: UUID,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> DebitAccountView:
    await department(s, actor, department_id)
    row = await s.get(DepartmentDebitAccount, department_id)
    return DebitAccountView(
        version=row.version if row else 0,
        data=DebitAccount.model_validate(row.data) if row else None,
    )


@router.put("/departments/{department_id}/debit-account", response_model=DebitAccountView)
async def put_department_account(
    department_id: UUID,
    body: DebitAccountUpdate,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> DebitAccountView:
    dept, entity = await department(s, actor, department_id, lock=True)
    if not dept.active or not entity.active:
        raise DomainError(
            "ACCESS_DENIED",
            "Enable this company and department before configuring its sub-account.",
            403,
        )
    row = await s.get(DepartmentDebitAccount, department_id, populate_existing=True)
    if (row.version if row else 0) != body.expected_version:
        raise DomainError(
            "REVISION_CONFLICT", "The department bank details changed. Reload before saving."
        )
    if row:
        row.data = body.data.model_dump(mode="json")
        row.version += 1
    else:
        row = DepartmentDebitAccount(
            department_id=department_id, version=1, data=body.data.model_dump(mode="json")
        )
        s.add(row)
    await record_event(
        s,
        action="organisation.department_debit_account.updated",
        actor_id=actor.id,
        resource_id=department_id,
        entity_id=entity.id,
        details=AuditDetails(resource_type="organisation"),
    )
    return DebitAccountView(version=row.version, data=body.data)
