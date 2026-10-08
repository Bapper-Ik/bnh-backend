from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.read import AuditPage, search_events
from app.audit.service import record_event
from app.core.database import get_session
from app.history.filters import AuditFilters
from app.identity.service import Actor, current_actor, require_permission

router = APIRouter(prefix="/api/v1/audit-events", tags=["Audit Log"])


@router.get("", response_model=AuditPage)
async def audit_events(
    filters: Annotated[AuditFilters, Query()],
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> AuditPage:
    require_permission(actor, "audit:read")
    result = await search_events(s, actor, filters)
    await record_event(s, action="audit.search.success", actor_id=actor.id)
    return result
