import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.core.config import Settings, get_settings
from app.core.database import check_runtime, make_engine
from app.core.errors import install_errors

logger = logging.getLogger("custodian")


class Health(BaseModel):
    status: str


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(config)
        try:
            try:
                await check_runtime(engine)
            except Exception:
                logger.error("runtime.configuration_validation.failure")
                raise
            logger.info("runtime.configuration_validation.success")
            app.state.sessions = async_sessionmaker(engine, expire_on_commit=False)
            app.state.engine = engine
            app.state.settings = config
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Custodian by Brendan", version="0.1.0", lifespan=lifespan)
    install_errors(app)

    @app.middleware("http")
    async def request_context(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/health/live", response_model=Health)
    async def live() -> Health:
        return Health(status="alive")

    @app.get("/api/v1/health/ready", response_model=Health, responses={503: {"model": Health}})
    async def ready(request: Request) -> Health | JSONResponse:
        try:
            await check_runtime(request.app.state.engine)
        except Exception:
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return Health(status="ready")

    return app
