"""Exercise the runtime contract through real transactions and app restarts."""

from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Identity, get_session, make_engine
from app.core.errors import DomainError
from app.runtime import create_app


def test_missing_database_secret_fails_closed(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None, environment="production")


def test_production_placeholder_password_fails():
    with pytest.raises(ValidationError, match="configured database credentials"):
        Settings(
            _env_file=None,
            environment="production",
            database_url=SecretStr("postgresql+asyncpg://app:REPLACE_ME@localhost/db"),
            allowed_origins=["https://staff.example.com"],
            cookie_secure=True,
        )


def test_app(settings):
    """Test-only routes; the delivered runtime exposes no identity CRUD endpoint."""
    app = create_app(settings)
    session_dep = Annotated[AsyncSession, Depends(get_session, scope="function")]

    @app.post("/test-record/{record_id}")
    async def write(record_id: UUID, session: session_dep, fail: bool = False):
        session.add(Identity(id=record_id, display_name="Synthetic runtime check"))
        await session.flush()
        if fail:
            raise DomainError("TEST_ROLLBACK", "Expected test failure")
        return {"id": str(record_id)}

    @app.get("/test-record/{record_id}")
    async def read(record_id: UUID, session: session_dep):
        record = await session.get(Identity, record_id)
        if not record:
            raise DomainError("NOT_FOUND", "No record", 404)
        return {
            "id": str(record.id),
            "version": record.version,
            "created_at": record.created_at.isoformat(),
        }

    return app


test_app.__test__ = False


async def test_client_reconnect_after_application_restart(settings):
    record_id = uuid4()
    app = test_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            assert (await client.post(f"/test-record/{record_id}")).status_code == 200
    # A new app, engine, pool, session factory and HTTP client must see the same record.
    restarted = test_app(settings)
    async with restarted.router.lifespan_context(restarted):
        async with AsyncClient(
            transport=ASGITransport(restarted), base_url="http://test"
        ) as client:
            response = await client.get(f"/test-record/{record_id}")
            assert response.status_code == 200
            assert response.json()["id"] == str(record_id)
            assert response.json()["version"] == 1
            assert response.json()["created_at"].endswith("+00:00")


async def test_expected_api_error_rolls_back_flushed_write(settings):
    record_id = uuid4()
    app = test_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.post(f"/test-record/{record_id}?fail=true")
            assert response.status_code == 409
            assert response.json()["code"] == "TEST_ROLLBACK"
            assert response.json()["request_id"] == response.headers["x-request-id"]
            assert (await client.get(f"/test-record/{record_id}")).status_code == 404


async def test_unavailable_database_readiness_is_safe(settings):
    app = create_app(settings)
    unavailable = make_engine(
        settings.model_copy(
            update={
                "database_url": SecretStr(
                    "postgresql+asyncpg://synthetic:private-test-password@127.0.0.1:1/unavailable_test"
                )
            }
        )
    )
    try:
        async with app.router.lifespan_context(app):
            app.state.engine = unavailable
            async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
                response = await client.get("/api/v1/health/ready")
                assert response.status_code == 503
                assert response.json() == {"status": "unavailable"}
                assert (await client.get("/api/v1/health/live")).status_code == 200
    finally:
        await unavailable.dispose()
