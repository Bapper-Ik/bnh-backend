from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.core.database import Identity, check_runtime, make_engine
from app.runtime import create_app


async def test_persistence_reconnect_and_rollback(settings, engine, sessions):
    identity_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(Identity(id=identity_id, display_name="Synthetic persistence test"))
    await engine.dispose()
    fresh = make_engine(settings)
    async with async_sessionmaker(fresh)() as session:
        identity = await session.get(Identity, identity_id)
        assert identity.display_name == "Synthetic persistence test"
    failed_id = uuid4()
    with pytest.raises(RuntimeError):
        async with sessions() as session, session.begin():
            session.add(Identity(id=failed_id, display_name="Rollback"))
            await session.flush()
            raise RuntimeError("Forced failure")
    async with sessions() as session:
        assert await session.get(Identity, failed_id) is None
    await fresh.dispose()


async def test_runtime_checks_schema_access(engine):
    await check_runtime(engine)


async def test_health_across_app_restart(settings):
    for _ in range(2):
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
                assert (await client.get("/api/v1/health/ready")).json() == {"status": "ready"}
                response = await client.get("/api/v1/health/live")
                assert response.headers["cache-control"] == "no-store"
                assert response.json() == {"status": "alive"}


def test_production_requires_explicit_secure_configuration():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            environment="production",
            database_url=SecretStr("postgresql+asyncpg://app:REPLACE_ME@localhost/db"),
        )


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+asyncpg"])
def test_render_database_urls_use_the_async_driver_without_changing_credentials(scheme):
    settings = Settings(
        _env_file=None,
        database_url=f"{scheme}://owner:synthetic%40password@localhost/custodian_dev",
    )
    from sqlalchemy.engine import make_url

    url = make_url(settings.database_url.get_secret_value())
    assert url.drivername == "postgresql+asyncpg"
    assert url.username == "owner"
    assert url.password == "synthetic@password"
    assert url.database == "custodian_dev"
