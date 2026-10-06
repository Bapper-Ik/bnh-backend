"""One-time controlled provisioning. Password is prompted, never a command-line argument."""

import asyncio
import getpass

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.audit.service import record_event
from app.core.config import get_settings
from app.core.database import Identity, make_engine
from app.identity.models import Account
from app.identity.service import hasher


async def main() -> None:
    email, name = input("Operator email: ").strip().lower(), input("Full name: ").strip()
    password = getpass.getpass("Password (at least 12 characters): ")
    if len(password) < 12 or password != getpass.getpass("Confirm password: ") or not name:
        raise SystemExit("Invalid name/password or confirmation mismatch")
    email = str(TypeAdapter(EmailStr).validate_python(email)).lower()
    engine = make_engine(get_settings())
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            await session.execute(text("SELECT pg_advisory_xact_lock(67200601)"))
            if await session.scalar(select(Account.id).limit(1)):
                raise SystemExit("Accounts already exist; use controlled staff administration")
            identity = Identity(display_name=name)
            session.add(identity)
            await session.flush()
            session.add(
                Account(
                    identity_id=identity.id,
                    email=email,
                    password_hash=hasher.hash(password),
                    permissions=["staff:manage", "organisation:manage", "office_assignment:manage"],
                )
            )
            await record_event(
                session, action="identity.created", actor_id=None, resource_id=identity.id
            )
        print("Configuration operator created. This grants no financial approval authority.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
