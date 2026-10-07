from uuid import UUID

from fastapi import FastAPI, Request

from app.audit.service import AuditDetails, record_event
from app.auth_app import create_app as create_auth
from app.core.config import Settings
from app.core.errors import DomainError
from app.organisation.lifecycle import router as lifecycle_router
from app.organisation.router import router
from app.organisation.staff import router as staff_router


def create_app(settings: Settings | None = None) -> FastAPI:
    app = create_auth(settings)

    async def record_rejected_action(request: Request, exc: DomainError) -> None:
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and request.url.path.startswith("/api/v1/organisation/offices")
            or (
                request.method == "POST"
                and request.url.path.startswith("/api/v1/staff/")
                and "/offices" in request.url.path
            )
        ):
            async with request.app.state.sessions() as session, session.begin():
                await record_event(
                    session,
                    action="office.assignment_failed",
                    actor_id=getattr(request.state, "actor_id", None),
                    correlation_id=UUID(request.state.request_id),
                    details=AuditDetails(outcome="denied"),
                )

    app.state.record_rejected_action = record_rejected_action
    app.include_router(router)
    app.include_router(lifecycle_router)
    app.include_router(staff_router)
    return app
