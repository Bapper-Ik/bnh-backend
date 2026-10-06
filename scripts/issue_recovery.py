"""Controlled recovery handoff; plaintext token never appears in logs or stdout."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

from pydantic import EmailStr, TypeAdapter
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.core.database import make_engine
from app.identity.recovery import issue_recovery


async def main() -> None:
    email = str(
        TypeAdapter(EmailStr).validate_python(input("Verified staff email: ").strip())
    ).lower()
    settings = get_settings()
    engine = make_engine(settings)
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            token = await issue_recovery(session, email)
        directory = Path(".state/recovery")
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        path = directory / f"{uuid4()}.txt"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(f"{settings.allowed_origins[0]}/recover#token={token}\n")
        print(f"Recovery link saved privately to {path}. Expires in 30 minutes.")
        print(
            "Hand it to the verified staff member through an approved private channel, then delete this file."
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
