"""Loopback browser fixture with private captured mail; never uses a live provider."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import uvicorn
from dotenv import dotenv_values
from pydantic import SecretStr
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.core.database import Identity, make_engine
from app.identity.models import Account
from app.identity.service import hasher
from app.organisation.models import Department, Entity, Membership
from app.vendor_app import create_app


async def prepare() -> Settings:
    values = dotenv_values(".env.test")
    url = str(values["DATABASE_URL"])
    parsed = make_url(url)
    if parsed.host != "127.0.0.1" or not (parsed.database or "").endswith("_test"):
        raise RuntimeError("Browser fixtures require an isolated loopback test database")
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=SecretStr(url),
        database_ssl=False,
        cookie_secure=False,
        allowed_origins=["http://127.0.0.1:4173"],
        mail_enabled=True,
        mail_from="synthetic-sender@example.com",
        resend_api_key=SecretStr("synthetic-not-a-provider-key"),
        account_link_secret=SecretStr(uuid4().hex + uuid4().hex),
        frontend_origin="http://127.0.0.1:4173",
    )
    engine = make_engine(settings)
    people = []
    password = "Synthetic-browser-password-" + uuid4().hex
    async with async_sessionmaker(engine, expire_on_commit=False)() as session, session.begin():
        entity = Entity(name="Synthetic browser company " + uuid4().hex)
        session.add(entity)
        await session.flush()
        department = Department(entity_id=entity.id, name="Operations")
        session.add(department)
        await session.flush()
        for role in (
            "owner",
            "peer",
            "readonly",
            "access",
            "inviter",
            "admin",
            "admin_peer",
            "managed",
        ):
            identity = Identity(display_name="Synthetic " + role)
            session.add(identity)
            await session.flush()
            email = f"{role}-{uuid4().hex}@example.com"
            session.add(
                Account(
                    identity_id=identity.id,
                    email=email,
                    password_hash=hasher.hash(password),
                    permissions=["staff:manage", "organisation:manage", "office_assignment:manage"]
                    if role in {"admin", "admin_peer"}
                    else ["staff:manage"]
                    if role in {"access", "inviter"}
                    else [],
                    read_only=role == "readonly",
                )
            )
            session.add(
                Membership(
                    identity_id=identity.id, entity_id=entity.id, department_id=department.id
                )
            )
            people.append({"role": role, "email": email})
        fixture = {
            "people": people,
            "password": password,
            "entity": str(entity.id),
            "entity_name": entity.name,
            "department": str(department.id),
        }
    await engine.dispose()
    target = Path(
        os.environ.get("CUSTODIAN_BROWSER_FIXTURE", "../bnh-ui/test-results/vendor-fixture.json")
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(fixture))
    target.chmod(0o600)
    return settings


if __name__ == "__main__":
    config = asyncio.run(prepare())

    async def capture_mail(settings, job, token, purpose):
        assert settings.environment == "test"
        fixture = Path(
            os.environ.get(
                "CUSTODIAN_BROWSER_FIXTURE", "../bnh-ui/test-results/vendor-fixture.json"
            )
        )
        directory = fixture.parent / "mailbox"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = directory / (hashlib.sha256(job.recipient.encode()).hexdigest() + ".json")
        path.write_text(
            json.dumps({"purpose": purpose, "url": f"{job.link_origin}/recover#token={token}"})
        )
        path.chmod(0o600)

    app = create_app(config)
    app.state.account_email_sender = capture_mail
    uvicorn.run(app, host="127.0.0.1", port=8017, access_log=False)
