from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import AuditDetails, record_event
from app.core.database import get_session
from app.core.errors import DomainError
from app.identity.service import Actor, current_actor, require_permission
from app.organisation.models import Entity
from app.transfers.models import CompanyDebitAccount
from app.transfers.schemas import DebitAccount, DebitAccountUpdate, DebitAccountView

router = APIRouter(prefix="/api/v1/organisation/entities", tags=["Company bank instructions"])


async def company(s: AsyncSession, actor: Actor, entity_id: UUID, lock: bool = False) -> Entity:
    require_permission(actor, "organisation:manage")
    query = select(Entity).where(Entity.id == entity_id)
    if lock:
        query = query.with_for_update()
    row = await s.scalar(query)
    if not row:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Company not found.", 404)
    return row


@router.get("/{entity_id}/debit-account", response_model=DebitAccountView)
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


@router.put("/{entity_id}/debit-account", response_model=DebitAccountView)
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
