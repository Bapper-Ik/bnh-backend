"""Prepare Custodian's schema using DATABASE_URL; preserve existing schemas/roles."""

import asyncio

from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import make_engine


async def prepare() -> None:
    engine = make_engine(get_settings())
    try:
        async with engine.begin() as connection:
            # Historical migrations grant to this role. Fresh installations need
            # the role, but the application uses DATABASE_URL rather than its login.
            await connection.execute(
                text("""
                DO $$ BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custodian_app') THEN
                        CREATE ROLE custodian_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
                    END IF;
                END $$;
            """)
            )
            await connection.execute(text("CREATE SCHEMA IF NOT EXISTS custodian"))
            await connection.execute(text("REVOKE ALL ON SCHEMA custodian FROM PUBLIC"))
    finally:
        await engine.dispose()
    print("Custodian schema is ready; DATABASE_URL and existing role credentials are unchanged.")


if __name__ == "__main__":
    asyncio.run(prepare())
