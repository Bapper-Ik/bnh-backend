from uuid import UUID

from fastapi import FastAPI, Request

from app.access.router import router
from app.audit.service import AuditDetails, record_event
from app.core.config import Settings
from app.core.errors import DomainError
from app.org_app import create_app as create_org


def create_app(settings: Settings | None = None) -> FastAPI:
    app = create_org(settings)
    previous = app.state.record_rejected_action

    async def rejected(request: Request, exc: DomainError) -> None:
        await previous(request, exc)
        permission_change = (
            request.url.path == "/api/v1/access/review-grants" and request.method == "POST"
        )
        if permission_change or exc.code in {
            "ACCESS_DENIED",
            "RESOURCE_NOT_AVAILABLE",
            "AUTHENTICATION_REQUIRED",
        }:
            async with app.state.sessions() as s, s.begin():
                await record_event(
                    s,
                    action="access.permission_change.failure"
                    if permission_change
                    else "access.denied.failure",
                    actor_id=getattr(request.state, "actor_id", None),
                    correlation_id=UUID(request.state.request_id),
                    details=AuditDetails(outcome="denied"),
                )

    app.state.record_rejected_action = rejected
    app.include_router(router)
    return app
