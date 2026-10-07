import os
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from dotenv import dotenv_values
from pydantic import SecretStr
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import Settings
from app.core.database import make_engine


@pytest.fixture(scope="session")
def settings() -> Settings:
    path = Path(".env.test")
    if not path.exists():
        pytest.fail(
            "An isolated .env.test database is required. Never run integration tests on development/production."
        )
    values = dotenv_values(path)
    url = str(values["DATABASE_URL"])
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("Test database name must end with _test")
    return Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(url),
        database_ssl=values.get("DATABASE_SSL") == "true",
        cookie_secure=False,
    )


@pytest.fixture(scope="session", autouse=True)
def migrate(settings: Settings) -> None:
    values = {k: str(v) for k, v in dotenv_values(".env.test").items() if v is not None}
    values["DATABASE_URL"] = values["TEST_DATABASE_OWNER_URL"]
    for _ in range(2):
        subprocess.run(
            [".venv/bin/alembic", "upgrade", "head"], env={**os.environ, **values}, check=True
        )


@pytest.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = make_engine(settings)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
