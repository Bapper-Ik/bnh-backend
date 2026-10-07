"""Fresh isolated databases prove migrations rather than relying on existing state."""

import asyncio
import os
import subprocess
from uuid import uuid4

import asyncpg
import pytest
from dotenv import dotenv_values
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.core.database import check_runtime, make_engine
from app.runtime import create_app


async def test_fresh_database_migrates_twice_without_losing_records(settings):
    values = {key: value for key, value in dotenv_values(".env.test").items() if value is not None}
    owner_url = make_url(values["TEST_DATABASE_OWNER_URL"])
    assert (owner_url.database or "").endswith("_test")
    database = f"custodian_migrations_{uuid4().hex}_test"
    connect = dict(
        host=owner_url.host,
        port=owner_url.port,
        user=owner_url.username,
        password=owner_url.password,
        ssl="require" if settings.database_ssl else False,
    )
    owner = await asyncpg.connect(**connect, database=owner_url.database)
    try:
        await owner.execute(f'CREATE DATABASE "{database}"')
        fresh = await asyncpg.connect(**connect, database=database)
        try:
            await fresh.execute("CREATE TABLE public.unrelated (value text)")
            await fresh.execute("INSERT INTO public.unrelated VALUES ('preserved')")
            migration_url = owner_url.set(database=database).render_as_string(hide_password=False)
            runtime_url = (
                make_url(settings.database_url.get_secret_value())
                .set(database=database)
                .render_as_string(hide_password=False)
            )
            migration_env = {
                **os.environ,
                **values,
                # Plain Render URL works; the removed variable cannot select another DB.
                "DATABASE_URL": migration_url.replace("postgresql+asyncpg://", "postgresql://"),
                "MIGRATION_DATABASE_URL": "postgresql://unused:unused@127.0.0.1:1/unused",
            }
            for attempt in range(2):
                provision = await asyncio.to_thread(
                    subprocess.run,
                    [".venv/bin/python", "-m", "scripts.provision_database"],
                    env=migration_env,
                    capture_output=True,
                    text=True,
                )
                assert provision.returncode == 0, "Fresh-database provisioning failed"
                result = await asyncio.to_thread(
                    subprocess.run,
                    [".venv/bin/alembic", "upgrade", "head"],
                    env=migration_env,
                    capture_output=True,
                    text=True,
                )
                assert result.returncode == 0, "Fresh-database Alembic migration failed"
                if attempt == 0:
                    identity_id = uuid4()
                    await fresh.execute(
                        "INSERT INTO custodian.identities (id,display_name) VALUES ($1,'Synthetic migration check')",
                        identity_id,
                    )
            assert (
                await fresh.fetchval(
                    "SELECT display_name FROM custodian.identities WHERE id=$1", identity_id
                )
                == "Synthetic migration check"
            )
            assert await fresh.fetchval("SELECT value FROM public.unrelated") == "preserved"
            engine = make_engine(
                settings.model_copy(update={"database_url": SecretStr(runtime_url)})
            )
            try:
                await check_runtime(engine)
            finally:
                await engine.dispose()
        finally:
            await fresh.close()
    finally:
        # Only this test's randomly named, newly created database is removed.
        await owner.execute(f'DROP DATABASE IF EXISTS "{database}"')
        await owner.close()


async def test_runtime_accepts_the_same_owner_connection_used_for_migrations(settings):
    values = dotenv_values(".env.test")
    owner_engine = make_engine(
        settings.model_copy(
            update={"database_url": SecretStr(str(values["TEST_DATABASE_OWNER_URL"]))}
        )
    )
    try:
        await check_runtime(owner_engine)
        owner_settings = settings.model_copy(
            update={"database_url": SecretStr(str(values["TEST_DATABASE_OWNER_URL"]))}
        )
        app = create_app(owner_settings)
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
                assert (await client.get("/api/v1/health/ready")).json() == {"status": "ready"}
    finally:
        await owner_engine.dispose()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE custodian.audit_events SET action = action WHERE false",
        "DELETE FROM custodian.audit_events WHERE false",
        "TRUNCATE custodian.audit_events",
    ],
)
async def test_history_triggers_still_reject_mutations_with_owner_connection(settings, statement):
    values = dotenv_values(".env.test")
    engine = make_engine(
        settings.model_copy(
            update={"database_url": SecretStr(str(values["TEST_DATABASE_OWNER_URL"]))}
        )
    )
    try:
        async with engine.connect() as connection:
            with pytest.raises(DBAPIError, match="append-only|foreign key"):
                await connection.execute(text(statement))
            await connection.rollback()
    finally:
        await engine.dispose()
