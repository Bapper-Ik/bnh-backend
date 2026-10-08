import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from app.audit.models import AuditEvent
from app.audit.service import record_event
from app.identity.models import Account, LoginSession
from app.identity.recovery import issue_recovery
from app.identity.service import digest
from tests.identity.test_auth import account as account
from tests.identity.test_auth import auth_client as auth_client
from tests.identity.test_auth import sign_in

OLD = "Synthetic-test-password-2026"
NEW = "Synthetic-changed-password-2026"


async def test_profile_is_readonly_and_rechecks_organisation(context, organisation, sessions):
    from app.organisation.models import Membership, Office
    from tests.requisitions.test_workflow import sign_in as org_login

    c = context[0]
    person = organisation["people"]["hod"]
    await org_login(c, person)
    r = await c.get("/api/v1/auth/profile")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    data = r.json()
    assert len(data["memberships"]) == 1 and data["memberships"][0]["active"]
    assert data["offices"][0]["role"] == "hod"
    assert set(data) == {"name", "email", "read_only", "memberships", "offices"}
    assert (await c.patch("/api/v1/auth/profile", json={"department": "other"})).status_code == 405
    async with sessions() as s, s.begin():
        await s.execute(
            update(Membership).where(Membership.identity_id == person["id"]).values(active=False)
        )
        await s.execute(
            update(Office).where(Office.identity_id == person["id"]).values(active=False)
        )
    data = (await c.get("/api/v1/auth/profile")).json()
    assert not data["memberships"][0]["active"] and data["offices"] == []


# Reuse isolated organisation fixtures only for the profile journey.
from tests.requisitions.test_creation import context as context  # noqa: E402
from tests.requisitions.test_workflow import organisation as organisation  # noqa: E402


async def test_session_scope_pagination_expiry_and_individual_revocation(
    auth_client, account, sessions
):
    c = auth_client
    await sign_in(c, account)
    first_cookie = c.cookies.get("custodian_session")
    first = (await c.get("/api/v1/auth/sessions")).json()["items"][0]["id"]
    await sign_in(c, account)
    r = await c.get("/api/v1/auth/sessions?limit=1")
    assert r.headers["cache-control"] == "no-store"
    page = r.json()
    assert page["total"] == 2 and len(page["items"]) == 1 and page["items"][0]["current"]
    assert set(page["items"][0]) == {"id", "created_at", "expires_at", "current"}
    assert (await c.get("/api/v1/auth/sessions?limit=1&offset=1")).json()["items"][0]["id"] == first
    assert (await c.post(f"/api/v1/auth/sessions/{first}/revoke")).status_code == 200
    assert (await c.post(f"/api/v1/auth/sessions/{first}/revoke")).status_code == 200
    assert (
        await c.get("/api/v1/auth/me", headers={"cookie": f"custodian_session={first_cookie}"})
    ).status_code == 401
    assert (await c.get("/api/v1/auth/sessions")).json()["total"] == 1
    assert (await c.post(f"/api/v1/auth/sessions/{uuid4()}/revoke")).status_code == 404
    async with sessions() as s, s.begin():
        s.add(
            LoginSession(
                account_id=account.id,
                token_hash=digest(str(uuid4())),
                csrf_hash=digest(str(uuid4())),
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
                authenticated_at=datetime.now(UTC),
            )
        )
    assert (await c.get("/api/v1/auth/sessions")).json()["total"] == 1
    current = page["items"][0]["id"]
    assert (await c.post(f"/api/v1/auth/sessions/{current}/revoke")).status_code == 200
    assert (await c.get("/api/v1/auth/profile")).status_code == 401


async def test_cannot_revoke_another_person_and_csrf_is_required(auth_client, account, sessions):
    from app.core.database import Identity
    from app.identity.service import hasher

    c = auth_client
    async with sessions() as s, s.begin():
        identity = Identity(display_name="Other synthetic staff")
        s.add(identity)
        await s.flush()
        other = Account(
            identity_id=identity.id, email=f"{uuid4()}@example.com", password_hash=hasher.hash(OLD)
        )
        s.add(other)
        await s.flush()
    await sign_in(c, other)
    target = (await c.get("/api/v1/auth/sessions")).json()["items"][0]["id"]
    await sign_in(c, account)
    assert (await c.get("/api/v1/auth/sessions")).json()["total"] == 1
    assert (await c.post(f"/api/v1/auth/sessions/{target}/revoke")).status_code == 404
    for path, body in (
        ("/sessions/revoke-others", None),
        ("/password", {"current_password": OLD, "new_password": NEW}),
    ):
        assert (
            await c.post("/api/v1/auth" + path, json=body, headers={"x-csrf-token": ""})
        ).status_code == 403
        assert (
            await c.post(
                "/api/v1/auth" + path, json=body, headers={"origin": "https://untrusted.example"}
            )
        ).status_code == 403


async def test_revoke_others_preserves_current_and_readonly_can_secure_account(
    auth_client, account, sessions
):
    c = auth_client
    await sign_in(c, account)
    old = c.cookies.get("custodian_session")
    await sign_in(c, account)
    async with sessions() as s, s.begin():
        (await s.get(Account, account.id)).read_only = True
    assert (await c.post("/api/v1/auth/sessions/revoke-others")).status_code == 200
    assert (await c.get("/api/v1/auth/sessions")).json()["total"] == 1
    assert (
        await c.get("/api/v1/auth/me", headers={"cookie": f"custodian_session={old}"})
    ).status_code == 401
    assert (await c.get("/api/v1/auth/profile")).json()["read_only"]
    assert (
        await c.post("/api/v1/auth/password", json={"current_password": OLD, "new_password": NEW})
    ).status_code == 200


async def test_password_change_revokes_sessions_reset_links_and_audits_without_secrets(
    auth_client, account, sessions
):
    c = auth_client
    await sign_in(c, account)
    old = c.cookies.get("custodian_session")
    await sign_in(c, account)
    async with sessions() as s, s.begin():
        token = await issue_recovery(s, account.email)
    body = {"current_password": OLD, "new_password": NEW}
    assert (
        await c.post("/api/v1/auth/password", json={**body, "permissions": ["staff:manage"]})
    ).status_code == 422
    assert (
        await c.post("/api/v1/auth/password", json={**body, "new_password": "short"})
    ).status_code == 422
    assert (
        await c.post("/api/v1/auth/password", json={**body, "new_password": OLD})
    ).status_code == 422
    assert (await c.post("/api/v1/auth/password", json=body)).status_code == 200
    assert not c.cookies.get("custodian_session")
    assert (
        await c.get("/api/v1/auth/me", headers={"cookie": f"custodian_session={old}"})
    ).status_code == 401
    assert (
        await c.post("/api/v1/auth/recover", json={"token": token, "password": OLD})
    ).status_code == 400
    assert (await sign_in(c, account)).status_code == 401
    assert (await sign_in(c, account, NEW)).status_code == 200
    async with sessions() as s:
        events = (
            await s.scalars(select(AuditEvent).where(AuditEvent.resource_id == account.identity_id))
        ).all()
        assert any(e.action == "auth.password_changed" for e in events)
        assert all(
            all(secret not in str(e.details) for secret in (OLD, NEW, token, old)) for e in events
        )


async def test_wrong_current_password_is_persistently_throttled(auth_client, account):
    c = auth_client
    await sign_in(c, account)
    for _ in range(5):
        r = await c.post(
            "/api/v1/auth/password", json={"current_password": "wrong", "new_password": NEW}
        )
        assert r.status_code == 400 and r.json()["code"] == "PASSWORD_INCORRECT"
    assert (
        await c.post("/api/v1/auth/password", json={"current_password": OLD, "new_password": NEW})
    ).status_code == 429
    assert (await c.get("/api/v1/auth/me")).status_code == 200


async def test_password_change_rolls_back_when_mandatory_audit_fails(
    auth_client, account, sessions, monkeypatch
):
    await sign_in(auth_client, account)

    async def fail(s, **kwargs):
        return await record_event(s, action="auth.password_changed", actor_id=uuid4())

    monkeypatch.setattr("app.identity.security.record_event", fail)
    r = await auth_client.post(
        "/api/v1/auth/password", json={"current_password": OLD, "new_password": NEW}
    )
    assert r.status_code == 503
    assert (await auth_client.get("/api/v1/auth/me")).status_code == 200
    assert (await sign_in(auth_client, account)).status_code == 200


@pytest.mark.parametrize("method", ["get", "post"])
async def test_session_waiting_on_account_lock_rechecks_committed_revocation(
    auth_client, account, sessions, method
):
    c = auth_client
    await sign_in(c, account)
    async with sessions() as s, s.begin():
        await s.scalar(select(Account).where(Account.id == account.id).with_for_update())
        call = (
            c.get("/api/v1/auth/profile")
            if method == "get"
            else c.post("/api/v1/auth/sessions/revoke-others")
        )
        task = asyncio.create_task(call)
        await asyncio.sleep(0.15)
        assert not task.done()
        await s.execute(
            update(LoginSession).where(LoginSession.account_id == account.id).values(revoked=True)
        )
    assert (await asyncio.wait_for(task, 10)).status_code == 401
