from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.service import get_scoped_request
from app.audit.service import record_event
from app.core.database import get_session
from app.history.schemas import HistoryPage
from app.history.service import history_page
from app.identity.service import Actor, current_actor

router = APIRouter(prefix="/api/v1/requisitions", tags=["Request history"])


@router.get("/{request_id}/history", response_model=HistoryPage)
async def history(
    request_id: UUID,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    revision: int | None = Query(default=None, ge=1),
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> HistoryPage:
    req = await get_scoped_request(s, request_id, actor)
    if revision is not None:
        from app.requisitions.service import get_revision

        await get_revision(s, req, revision)
    page = await history_page(s, req, actor, limit=limit, offset=offset, revision=revision)
    await record_event(
        s,
        action="requisition.history_view.success",
        actor_id=actor.id,
        resource_id=req.id,
        entity_id=req.entity_id,
    )
    return page
