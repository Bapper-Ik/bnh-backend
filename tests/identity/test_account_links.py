import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import select, update

from app.audit.models import AuditEvent
from app.auth_app import create_app
from app.core.config import Settings
from app.core.database import Identity
from app.identity.email_delivery import deliver_one, link_token, send_resend
from app.identity.models import Account, AccountEmail, RecoveryToken
from app.identity.service import hasher

PASSWORD = "Synthetic-account-password-2026"
NEW_PASSWORD = "Synthetic-replacement-password-2026"


@pytest.fixture
async def links(settings, sessions):
    config = settings.model_copy(
        update={
            "mail_enabled": True,
            "mail_from": f"{uuid4()}@example.com",
            "resend_api_key": SecretStr("synthetic-provider-key"),
            "account_link_secret": SecretStr(uuid4().hex + uuid4().hex),
            "frontend_origin": "http://localhost:5173",
        }
    )
    async with sessions() as s, s.begin():
        identity = Identity(display_name="Synthetic account operator")
        s.add(identity)
        await s.flush()
        account = Account(
            identity_id=identity.id,
            email=f"{uuid4()}@example.com",
            password_hash=hasher.hash(PASSWORD),
            permissions=["staff:manage"],
        )
        s.add(account)
        await s.flush()
    app = create_app(config)
    app.state.account_email_worker = (
        False  # Delivery is exercised explicitly; never contact real recipients.
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app),
            base_url="http://test",
            headers={"origin": "http://localhost:5173"},
        ) as client,
    ):
        yield {"app": app, "client": client, "account": account, "settings": config}
    async with sessions() as s, s.begin():
        await s.execute(
            update(AccountEmail)
            .where(AccountEmail.sender == str(config.mail_from), AccountEmail.status == "pending")
            .values(status="cancelled")
        )


async def sign_in(context):
    response = await context["client"].post(
        "/api/v1/auth/login", json={"email": context["account"].email, "password": PASSWORD}
    )
    assert response.status_code == 200
    context["client"].headers["x-csrf-token"] = context["client"].cookies.get("custodian_csrf")


async def latest_token(context, sessions, email=None):
    async with sessions() as s:
        token = await s.scalar(
            select(RecoveryToken)
            .join(Account, Account.id == RecoveryToken.account_id)
            .where(Account.email == (email or context["account"].email))
            .order_by(RecoveryToken.created_at.desc())
            .limit(1)
        )
        assert token
        return token, link_token(context["settings"], token.id)


async def test_public_request_is_generic_throttled_and_contains_no_link(links, sessions):
    client = links["client"]
    known = await client.post(
        "/api/v1/auth/forgot-password", json={"email": links["account"].email}
    )
    unknown = await client.post(
        "/api/v1/auth/forgot-password", json={"email": f"{uuid4()}@example.com"}
    )
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert "token" not in known.text
    for _ in range(4):
        assert (
            await client.post(
                "/api/v1/auth/forgot-password", json={"email": links["account"].email}
            )
        ).status_code == 202
    token, raw = await latest_token(links, sessions)
    async with sessions() as s:
        jobs = (
            await s.scalars(select(AccountEmail).where(AccountEmail.token_id == token.id))
        ).all()
        assert len(jobs) == 1
        assert raw != token.token_hash
        events = (
            await s.scalars(
                select(AuditEvent).where(AuditEvent.resource_id == links["account"].identity_id)
            )
        ).all()
        assert all(raw not in str(event.details) for event in events)
    assert (
        await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": links["account"].email},
            headers={"origin": "https://evil.example"},
        )
    ).status_code == 403


async def test_reset_revokes_sessions_and_link_is_single_use(links, sessions):
    await sign_in(links)
    old_cookie = links["client"].cookies.get("custodian_session")
    await links["client"].post(
        "/api/v1/auth/forgot-password", json={"email": links["account"].email}
    )
    _, raw = await latest_token(links, sessions)
    response = await links["client"].post("/api/v1/auth/link-status", json={"token": raw})
    assert response.json() == {"purpose": "reset"}
    assert (
        await links["client"].post(
            "/api/v1/auth/recover", json={"token": raw, "password": NEW_PASSWORD}
        )
    ).status_code == 200
    assert (
        await links["client"].get(
            "/api/v1/auth/me", headers={"cookie": f"custodian_session={old_cookie}"}
        )
    ).status_code == 401
    assert (
        await links["client"].post(
            "/api/v1/auth/recover", json={"token": raw, "password": PASSWORD}
        )
    ).status_code == 400
    assert (
        await links["client"].post(
            "/api/v1/auth/login", json={"email": links["account"].email, "password": NEW_PASSWORD}
        )
    ).status_code == 200


async def test_invitation_requires_manager_and_activation_grants_no_authority(links, sessions):
    client = links["client"]
    email = f"{uuid4()}@example.com"
    body = {"name": "Synthetic invitee", "email": email}
    assert (await client.post("/api/v1/auth/invitations", json=body)).status_code == 401
    await sign_in(links)
    assert (
        await client.post(
            "/api/v1/auth/invitations", json={**body, "permissions": ["staff:manage"]}
        )
    ).status_code == 422
    response = await client.post("/api/v1/auth/invitations", json=body)
    assert response.status_code == 201
    assert "token" not in response.text and "password" not in response.text
    token, raw = await latest_token(links, sessions, email)
    async with sessions() as s, s.begin():
        account = await s.get(Account, token.account_id)
        assert account.password_pending and account.permissions == []
        account.password_hash = hasher.hash(NEW_PASSWORD)
    assert (
        await client.post("/api/v1/auth/login", json={"email": email, "password": NEW_PASSWORD})
    ).status_code == 401
    assert (await client.post("/api/v1/auth/link-status", json={"token": raw})).json() == {
        "purpose": "activate"
    }
    assert (
        await client.post("/api/v1/auth/recover", json={"token": raw, "password": NEW_PASSWORD})
    ).status_code == 200
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": NEW_PASSWORD})
    assert login.status_code == 200
    assert login.json()["permissions"] == []
    assert (await client.post("/api/v1/auth/invitations", json=body)).status_code == 403


@pytest.mark.parametrize("invalid", ["expired", "disabled", "superseded"])
async def test_invalid_links_are_rejected_before_and_during_password_change(
    links, sessions, invalid
):
    client = links["client"]
    await client.post("/api/v1/auth/forgot-password", json={"email": links["account"].email})
    token, raw = await latest_token(links, sessions)
    async with sessions() as s, s.begin():
        if invalid == "disabled":
            (await s.get(Account, token.account_id)).active = False
        elif invalid == "expired":
            (await s.get(RecoveryToken, token.id)).expires_at = datetime.now(UTC) - timedelta(
                seconds=1
            )
        else:
            (await s.get(RecoveryToken, token.id)).consumed_at = datetime.now(UTC)
    assert (await client.post("/api/v1/auth/link-status", json={"token": raw})).status_code == 400
    assert (
        await client.post("/api/v1/auth/recover", json={"token": raw, "password": NEW_PASSWORD})
    ).status_code == 400


async def test_delivery_retries_same_link_and_idempotency_identity(links, sessions):
    await links["client"].post(
        "/api/v1/auth/forgot-password", json={"email": links["account"].email}
    )
    attempts = []

    async def sender(config, job, token, purpose):
        attempts.append((job.id, token, purpose))
        if len(attempts) == 1:
            raise RuntimeError("Synthetic provider outage")

    assert await deliver_one(sessions, links["settings"], sender)
    async with sessions() as s, s.begin():
        job = await s.get(AccountEmail, attempts[0][0])
        assert job.status == "pending" and job.attempts == 1
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
    assert await deliver_one(sessions, links["settings"], sender)
    assert attempts[0] == attempts[1]
    async with sessions() as s:
        job = await s.get(AccountEmail, attempts[0][0])
        assert job.status == "accepted" and job.attempts == 2


async def test_two_workers_send_one_job_once(links, sessions):
    await links["client"].post(
        "/api/v1/auth/forgot-password", json={"email": links["account"].email}
    )
    sent = []

    async def sender(config, job, token, purpose):
        sent.append(job.id)
        await asyncio.sleep(0.05)

    await asyncio.gather(
        deliver_one(sessions, links["settings"], sender),
        deliver_one(sessions, links["settings"], sender),
    )
    assert len(sent) == 1


async def test_consumed_link_is_never_sent(links, sessions):
    await links["client"].post(
        "/api/v1/auth/forgot-password", json={"email": links["account"].email}
    )
    _, raw = await latest_token(links, sessions)
    await links["client"].post(
        "/api/v1/auth/recover", json={"token": raw, "password": NEW_PASSWORD}
    )
    sent = []

    async def sender(*args):
        sent.append(args)

    await deliver_one(sessions, links["settings"], sender)
    assert sent == []


async def test_disabled_email_does_not_pretend_to_queue(settings):
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app),
            base_url="http://test",
            headers={"origin": "http://localhost:5173"},
        ) as client,
    ):
        assert (
            await client.post(
                "/api/v1/auth/forgot-password", json={"email": "synthetic@example.com"}
            )
        ).status_code == 503


async def test_resend_adapter_sends_stable_idempotency_key_and_never_follows_redirects(
    links, monkeypatch
):
    captured = []

    def transport(request):
        captured.append(request)
        return httpx.Response(200, json={"id": "synthetic"})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(transport), **kw)
    )
    job = AccountEmail(
        id=uuid4(),
        recipient="synthetic@example.com",
        sender="sender@example.com",
        link_origin="https://custodian.example.com",
    )
    await send_resend(links["settings"], job, "a" * 64, "reset")
    assert captured[0].url == "https://api.resend.com/emails"
    assert captured[0].headers["idempotency-key"] == f"custodian-account-link/{job.id}"
    assert b"/recover#token=" in captured[0].content


@pytest.mark.parametrize(
    "override",
    [
        {"account_link_secret": None},
        {"account_link_secret": SecretStr("short")},
        {"resend_api_key": None},
        {"mail_from": None},
        {"frontend_origin": "https://untrusted.example.com"},
        {"frontend_origin": "http://localhost:5173/recover"},
    ],
)
def test_mail_configuration_requires_secret_and_exact_trusted_origin(settings, override):
    values = {
        **settings.model_dump(),
        "mail_enabled": True,
        "mail_from": "sender@example.com",
        "resend_api_key": SecretStr("synthetic"),
        "account_link_secret": SecretStr("a" * 64),
        "frontend_origin": "http://localhost:5173",
        **override,
    }
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


async def test_new_invitation_replaces_old_link_and_queue_is_atomic(links, sessions, monkeypatch):
    import app.identity.email_delivery as delivery

    await sign_in(links)
    email = f"{uuid4()}@example.com"
    body = {"name": "Synthetic invited staff", "email": email}
    assert (await links["client"].post("/api/v1/auth/invitations", json=body)).status_code == 201
    _, original = await latest_token(links, sessions, email)
    assert (await links["client"].post("/api/v1/auth/invitations", json=body)).status_code == 201
    assert (
        await links["client"].post("/api/v1/auth/link-status", json={"token": original})
    ).status_code == 400

    async def fail_event(*args, **kwargs):
        raise RuntimeError("Synthetic audit outage")

    monkeypatch.setattr(delivery, "record_event", fail_event)
    other = f"{uuid4()}@example.com"
    with pytest.raises(RuntimeError, match="Synthetic audit outage"):
        await links["client"].post(
            "/api/v1/auth/invitations", json={"name": "Synthetic other staff", "email": other}
        )
    async with sessions() as s:
        assert await s.scalar(select(Account.id).where(Account.email == other)) is None


async def test_pending_activation_is_not_an_actionable_officeholder(links, sessions):
    from app.organisation.models import Department, Entity, Membership, Office
    from app.organisation.service import active_offices

    async with sessions() as s, s.begin():
        entity = Entity(name=f"Synthetic pending company {uuid4()}")
        s.add(entity)
        await s.flush()
        department = Department(entity_id=entity.id, name="Operations")
        s.add(department)
        await s.flush()
        s.add(
            Membership(
                identity_id=links["account"].identity_id,
                entity_id=entity.id,
                department_id=department.id,
            )
        )
        s.add(
            Office(
                identity_id=links["account"].identity_id,
                entity_id=entity.id,
                role="md",
                valid_from=datetime.now(UTC) - timedelta(minutes=1),
                authorisation_reference="Synthetic pending office test",
            )
        )
        await s.flush()
        assert len(await active_offices(s, entity.id)) == 1
        (await s.get(Account, links["account"].id)).password_pending = True
        await s.flush()
        assert await active_offices(s, entity.id) == []
