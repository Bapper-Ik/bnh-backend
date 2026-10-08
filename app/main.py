from uuid import UUID

from fastapi import FastAPI, Request

from app.audit.service import AuditDetails, record_event
from app.core.config import Settings, get_settings
from app.core.errors import DomainError
from app.evidence.router import router as evidence_router
from app.evidence.storage import CloudinaryStorage
from app.requisitions.router import approvals_router
from app.requisitions.router import router as requisitions_router
from app.vendor_app import create_app as create_runtime


def create_app(settings: Settings | None = None) -> FastAPI:
    app = create_runtime(settings)
    app.state.individual_decisions_enabled = True
    app.include_router(requisitions_router)
    app.include_router(approvals_router)
    app.include_router(evidence_router)
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
            "signature.rejected"
            if path.endswith(("/actions", "/signing-challenges"))
            else "evidence.rejected"
            if "/attachments" in path
            else None
        )
        if action and request.method not in {"GET", "HEAD"}:
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
