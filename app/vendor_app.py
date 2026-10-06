from uuid import UUID

from fastapi import FastAPI, Request

from app.access_app import create_app as create_access
from app.audit.service import AuditDetails, record_event
from app.core.config import Settings
from app.core.errors import DomainError
from app.vendors.router import router


def create_app(settings: Settings | None = None) -> FastAPI:
    app = create_access(settings)
    previous = app.state.record_rejected_action

    async def rejected(request: Request, exc: DomainError) -> None:
        await previous(request, exc)
        if request.method == "PATCH" and request.url.path.startswith("/api/v1/vendors/"):
            async with app.state.sessions() as session, session.begin():
                await record_event(
                    session,
                    action="vendor.update_failed",
                    actor_id=getattr(request.state, "actor_id", None),
                    correlation_id=UUID(request.state.request_id),
                    details=AuditDetails(outcome="denied"),
                )

    app.state.record_rejected_action = rejected
    app.include_router(router)
    return app
