"""Fresh isolated databases prove migrations rather than relying on existing state."""

import asyncio
import os
import subprocess
from uuid import uuid4

import asyncpg
import pytest
from dotenv import dotenv_values
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from app.core.database import check_runtime, make_engine


async def test_fresh_database_migrates_twice_without_losing_records(settings):
    values = {key: value for key, value in dotenv_values(".env.test").items() if value is not None}
    owner_url = make_url(values["MIGRATION_DATABASE_URL"])
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
            await fresh.execute("CREATE SCHEMA custodian")
            migration_url = owner_url.set(database=database).render_as_string(hide_password=False)
            runtime_url = (
                make_url(settings.database_url.get_secret_value())
                .set(database=database)
                .render_as_string(hide_password=False)
            )
            migration_env = {
                **os.environ,
                **values,
                "MIGRATION_DATABASE_URL": migration_url,
                "DATABASE_URL": runtime_url,
            }
            for attempt in range(2):
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


async def test_runtime_rejects_migration_owner(settings):
    values = dotenv_values(".env.test")
    owner_engine = make_engine(
        settings.model_copy(
            update={"database_url": SecretStr(str(values["MIGRATION_DATABASE_URL"]))}
        )
    )
    try:
        with pytest.raises(RuntimeError, match="administrative privileges"):
            await check_runtime(owner_engine)
    finally:
        await owner_engine.dispose()
