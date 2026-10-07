import asyncio
import os

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import normalize_database_url
from app.core.database import Base

load_dotenv()
raw_url = os.environ.get("DATABASE_URL")
if not raw_url:
    raise RuntimeError("DATABASE_URL is required before running migrations")
url = normalize_database_url(raw_url)


def run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        compare_type=True,
        version_table_schema="custodian",
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def main() -> None:
    assert url
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"ssl": "require"}
        if os.environ.get("DATABASE_SSL", "true").lower() == "true"
        else {},
    )
    async with engine.connect() as connection:
        await connection.run_sync(run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(main())
