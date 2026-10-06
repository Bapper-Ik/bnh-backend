import asyncio
import os

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.database import Base

load_dotenv()
url = os.environ.get("MIGRATION_DATABASE_URL")
if not url:
    raise RuntimeError(
        "MIGRATION_DATABASE_URL is required; never migrate using runtime credentials"
    )


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
