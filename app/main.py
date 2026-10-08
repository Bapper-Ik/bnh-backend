import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from uuid import UUID

from fastapi import FastAPI, Request

from app.audit.router import router as audit_router
from app.audit.service import AuditDetails, record_event
from app.board.router import router as board_router
from app.core.config import Settings, get_settings
from app.core.errors import DomainError
from app.evidence.router import router as evidence_router
from app.evidence.storage import CloudinaryStorage
from app.history.router import router as history_router
from app.notifications.delivery import delivery_loop, send_resend
from app.notifications.router import router as notifications_router
from app.requisitions.router import approvals_router
from app.requisitions.router import router as requisitions_router
from app.vendor_app import create_app as create_runtime


def create_app(settings: Settings | None = None) -> FastAPI:
    app = create_runtime(settings)
    app.state.individual_decisions_enabled = True
    app.include_router(requisitions_router)
    app.include_router(approvals_router)
    app.include_router(evidence_router)
    app.include_router(board_router)
    app.include_router(history_router)
    app.include_router(audit_router)
    app.include_router(notifications_router)
    app.state.notification_sender = send_resend
    app.state.notification_worker = True
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with original_lifespan(application):
            worker = None
            if application.state.notification_worker:
                worker = asyncio.create_task(
                    delivery_loop(
                        application.state.sessions,
                        application.state.settings,
                        application.state.notification_sender,
                    )
                )
            try:
                yield
            finally:
                if worker:
                    worker.cancel()
                    with suppress(asyncio.CancelledError):
                        await worker

    app.router.lifespan_context = lifespan
    cfg = settings or get_settings()
    app.state.evidence_storage = CloudinaryStorage(cfg)
    app.state.uploads_enabled = bool(
        cfg.cloudinary_cloud_name and cfg.cloudinary_api_key and cfg.cloudinary_api_secret
    )
    previous = app.state.record_rejected_action

    async def rejected(request: Request, exc: DomainError) -> None:
        await previous(request, exc)
        path = request.url.path
        action = (
            "board.rejected"
            if "/board" in path
            else "signature.rejected"
            if path.endswith(("/actions", "/signing-challenges"))
            else "evidence.rejected"
            if "/attachments" in path
            else None
        )
        if path.endswith("/history"):
            action = "requisition.history_view.failure"
        elif path == "/api/v1/audit-events":
            action = "audit.search.failure"
        if action and (
            request.method not in {"GET", "HEAD"} or path.endswith(("/history", "/audit-events"))
        ):
            async with app.state.sessions() as session, session.begin():
                await record_event(
                    session,
                    action=action,
                    actor_id=getattr(request.state, "actor_id", None),
                    correlation_id=UUID(request.state.request_id),
                    details=AuditDetails(outcome="denied"),
                )

    app.state.record_rejected_action = rejected
    return app
