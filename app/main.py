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
from app.dashboard.router import router as dashboard_router
from app.evidence.router import router as evidence_router
from app.evidence.staging import cleanup_loop
from app.evidence.staging import router as staging_router
from app.evidence.storage import CloudinaryStorage
from app.exports.render import available as export_fonts_available
from app.exports.render import render as export_renderer
from app.exports.router import router as exports_router
from app.exports.worker import export_loop
from app.history.router import router as history_router
from app.notifications.delivery import delivery_loop, send_resend
from app.notifications.router import router as notifications_router
from app.requisitions.router import approvals_router
from app.requisitions.router import router as requisitions_router
from app.transfers.router import router as transfers_router
from app.vendor_app import create_app as create_runtime


def create_app(settings: Settings | None = None) -> FastAPI:
    app = create_runtime(settings)
    app.state.individual_decisions_enabled = True
    app.include_router(dashboard_router)
    app.include_router(requisitions_router)
    app.include_router(approvals_router)
    app.include_router(evidence_router)
    app.include_router(staging_router)
    app.include_router(board_router)
    app.include_router(history_router)
    app.include_router(audit_router)
    app.include_router(notifications_router)
    app.include_router(exports_router)
    app.include_router(transfers_router)
    app.state.export_worker = True
    app.state.export_fonts_available = export_fonts_available
    app.state.export_renderer = export_renderer
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
            export_worker = None
            if application.state.export_worker:
                export_worker = asyncio.create_task(
                    export_loop(
                        application.state.sessions,
                        application.state.settings,
                        application.state.evidence_storage,
                        application.state.export_renderer,
                    )
                )
            staging_worker = asyncio.create_task(cleanup_loop(application.state.sessions))
            try:
                yield
            finally:
                staging_worker.cancel()
                with suppress(asyncio.CancelledError):
                    await staging_worker
                if export_worker:
                    export_worker.cancel()
                    with suppress(asyncio.CancelledError):
                        await export_worker
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
            if "/attachments" in path or "/staged-attachments" in path
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
