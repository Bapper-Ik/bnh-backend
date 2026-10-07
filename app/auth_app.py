import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.core.config import Settings
from app.identity.access_links import router as links_router
from app.identity.email_delivery import delivery_loop, send_resend
from app.identity.router import router
from app.runtime import create_app as create_runtime


def create_app(settings: Settings | None = None) -> FastAPI:
    app = create_runtime(settings)
    app.state.account_email_sender = send_resend
    app.state.account_email_worker = True
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with original_lifespan(application):
            worker = None
            if application.state.settings.mail_enabled and application.state.account_email_worker:
                worker = asyncio.create_task(
                    delivery_loop(
                        application.state.sessions,
                        application.state.settings,
                        application.state.account_email_sender,
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
    app.include_router(router)
    app.include_router(links_router)
    return app
