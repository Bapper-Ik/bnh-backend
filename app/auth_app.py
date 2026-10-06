from fastapi import FastAPI

from app.core.config import Settings
from app.identity.router import router
from app.runtime import create_app as create_runtime


def create_app(settings: Settings | None = None) -> FastAPI:
    app = create_runtime(settings)
    app.include_router(router)
    return app
