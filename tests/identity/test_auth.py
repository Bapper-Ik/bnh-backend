from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.audit.service import record_event
from app.auth_app import create_app
from app.core.database import Identity
from app.identity.models import Account
from app.identity.service import hasher


@pytest.fixture
async def account(sessions):
    async with sessions() as s, s.begin():
        identity = Identity(display_name="Synthetic staff")
        s.add(identity)
        await s.flush()
        account = Account(
            identity_id=identity.id,
            email=f"{uuid4()}@example.com",
            password_hash=hasher.hash("Synthetic-test-password-2026"),
            permissions=[],
        )
        s.add(account)
        await s.flush()
        await record_event(s, action="identity.created", actor_id=None, resource_id=identity.id)
        return account


async def test_login_csrf_logout_and_revocation(settings, sessions, account):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app),
            base_url="http://test",
            headers={"origin": "http://localhost:5173"},
        ) as client:
            body = {"email": account.email, "password": "Synthetic-test-password-2026"}
            response = await client.post("/api/v1/auth/login", json=body)
            assert response.status_code == 200, response.text
            assert "password" not in response.text
            assert (await client.get("/api/v1/auth/me")).json()["id"] == str(account.identity_id)
            assert (await client.post("/api/v1/auth/logout")).status_code == 403
            token = client.cookies.get("custodian_session")
            csrf = client.cookies.get("custodian_csrf")
            assert (
                await client.post("/api/v1/auth/logout", headers={"x-csrf-token": csrf})
            ).status_code == 200
            assert (
                await client.get(
                    "/api/v1/auth/me", headers={"cookie": f"custodian_session={token}"}
                )
            ).status_code == 401


async def test_failed_login_throttle_persists(settings, account):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app),
            base_url="http://test",
            headers={"origin": "http://localhost:5173"},
        ) as client:
            for _ in range(5):
                response = await client.post(
                    "/api/v1/auth/login", json={"email": account.email, "password": "wrong"}
                )
                assert response.status_code == 401
            assert (
                await client.post(
                    "/api/v1/auth/login",
                    json={"email": account.email, "password": "Synthetic-test-password-2026"},
                )
            ).status_code == 429


async def test_disabled_account_cannot_reuse_session(settings, sessions, account):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app),
            base_url="http://test",
            headers={"origin": "http://localhost:5173"},
        ) as client:
            assert (
                await client.post(
                    "/api/v1/auth/login",
                    json={"email": account.email, "password": "Synthetic-test-password-2026"},
                )
            ).status_code == 200
            async with sessions() as s, s.begin():
                stored = await s.get(Account, account.id)
                stored.active = False
            assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_untrusted_origin_rejected(settings, account):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            assert (
                await client.post(
                    "/api/v1/auth/login",
                    json={"email": account.email, "password": "Synthetic-test-password-2026"},
                    headers={"origin": "https://untrusted.example"},
                )
            ).status_code == 403


@pytest.fixture
async def auth_client(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app),
            base_url="http://test",
            headers={"origin": "http://localhost:5173"},
        ) as client:
            yield client


async def sign_in(client, account, password="Synthetic-test-password-2026"):
    response = await client.post(
        "/api/v1/auth/login", json={"email": account.email, "password": password}
    )
    if response.status_code == 200:
        client.headers["x-csrf-token"] = client.cookies.get("custodian_csrf")
    return response


async def test_reauthentication_failures_persist_and_throttle(auth_client, account, sessions):
    from sqlalchemy import select

    from app.identity.models import LoginSession
    from app.identity.service import digest

    assert (await sign_in(auth_client, account)).status_code == 200
    async with sessions() as s:
        before = (
            await s.scalar(
                select(LoginSession).where(
                    LoginSession.token_hash == digest(auth_client.cookies.get("custodian_session"))
                )
            )
        ).authenticated_at
    for _ in range(5):
        assert (
            await auth_client.post("/api/v1/auth/reauthenticate", json={"password": "wrong"})
        ).status_code == 401
    assert (
        await auth_client.post(
            "/api/v1/auth/reauthenticate", json={"password": "Synthetic-test-password-2026"}
        )
    ).status_code == 429
    async with sessions() as s:
        after = (
            await s.scalar(
                select(LoginSession).where(
                    LoginSession.token_hash == digest(auth_client.cookies.get("custodian_session"))
                )
            )
        ).authenticated_at
        assert before == after


async def test_successful_reauthentication_refreshes_server_context(auth_client, account, sessions):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.identity.models import LoginSession
    from app.identity.service import digest

    assert (await sign_in(auth_client, account)).status_code == 200
    token_hash = digest(auth_client.cookies.get("custodian_session"))
    async with sessions() as s, s.begin():
        stored = await s.scalar(select(LoginSession).where(LoginSession.token_hash == token_hash))
        stored.authenticated_at = datetime.now(UTC) - timedelta(hours=1)
    assert (
        await auth_client.post(
            "/api/v1/auth/reauthenticate", json={"password": "Synthetic-test-password-2026"}
        )
    ).status_code == 200
    async with sessions() as s:
        stored = await s.scalar(select(LoginSession).where(LoginSession.token_hash == token_hash))
        assert datetime.now(UTC) - stored.authenticated_at < timedelta(seconds=10)


async def test_expired_and_disabled_accounts_cannot_authenticate(auth_client, account, sessions):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from app.identity.models import LoginSession

    assert (await sign_in(auth_client, account)).status_code == 200
    async with sessions() as s, s.begin():
        await s.execute(
            update(LoginSession)
            .where(LoginSession.account_id == account.id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert (await auth_client.get("/api/v1/auth/me")).status_code == 401
    async with sessions() as s, s.begin():
        (await s.get(Account, account.id)).active = False
    assert (await sign_in(auth_client, account)).status_code == 401


async def test_revoke_all_sessions_invalidates_old_cookie(auth_client, account):
    assert (await sign_in(auth_client, account)).status_code == 200
    old_token = auth_client.cookies.get("custodian_session")
    assert (await sign_in(auth_client, account)).status_code == 200
    assert (await auth_client.post("/api/v1/auth/sessions/revoke")).status_code == 200
    assert (
        await auth_client.get(
            "/api/v1/auth/me", headers={"cookie": f"custodian_session={old_token}"}
        )
    ).status_code == 401


async def test_account_provisioning_is_protected_and_never_grants_roles(
    auth_client, account, sessions
):
    assert (await sign_in(auth_client, account)).status_code == 200
    body = {
        "name": "Second synthetic staff",
        "email": f"{uuid4()}@example.com",
        "initial_password": "Distinct-test-password-2026",
    }
    assert (await auth_client.post("/api/v1/auth/accounts", json=body)).status_code == 403
    async with sessions() as s, s.begin():
        (await s.get(Account, account.id)).permissions = ["staff:manage"]
    assert (
        await auth_client.post(
            "/api/v1/auth/accounts", json={**body, "permissions": ["staff:manage"]}
        )
    ).status_code == 422
    response = await auth_client.post("/api/v1/auth/accounts", json=body)
    assert response.status_code == 201, response.text
    assert response.json()["permissions"] == []
    assert "password" not in response.text
    assert response.json()["id"] != str(account.identity_id)
    first_token = auth_client.cookies.get("custodian_session")
    second = await auth_client.post(
        "/api/v1/auth/login", json={"email": body["email"], "password": body["initial_password"]}
    )
    assert second.status_code == 200
    assert auth_client.cookies.get("custodian_session") != first_token
    assert (await auth_client.get("/api/v1/auth/me")).json()["id"] == response.json()["id"]
    assert (
        await auth_client.get(
            "/api/v1/auth/me", headers={"cookie": f"custodian_session={first_token}"}
        )
    ).json()["id"] == str(account.identity_id)


async def test_operator_revocation_requires_permission(auth_client, account, sessions):
    assert (await sign_in(auth_client, account)).status_code == 200
    path = f"/api/v1/auth/accounts/{account.identity_id}/revoke-sessions"
    assert (await auth_client.post(path)).status_code == 403
    async with sessions() as s, s.begin():
        (await s.get(Account, account.id)).permissions = ["staff:manage"]
    assert (await auth_client.post(path)).status_code == 200
    assert (await auth_client.get("/api/v1/auth/me")).status_code == 401


async def test_recovery_consumption_revokes_sessions_and_prevents_replay(
    auth_client, account, sessions
):
    from sqlalchemy import select

    from app.audit.models import AuditEvent
    from app.identity.models import RecoveryToken
    from app.identity.recovery import issue_recovery
    from app.identity.service import digest

    assert (await sign_in(auth_client, account)).status_code == 200
    async with sessions() as s, s.begin():
        token = await issue_recovery(s, account.email)
    async with sessions() as s:
        stored = await s.scalar(select(RecoveryToken).where(RecoveryToken.account_id == account.id))
        assert stored.token_hash == digest(token)
        assert stored.token_hash != token
    body = {"token": token, "password": "Recovered-test-password-2026"}
    assert (await auth_client.post("/api/v1/auth/recover", json=body)).status_code == 200
    assert (await auth_client.get("/api/v1/auth/me")).status_code == 401
    assert (await auth_client.post("/api/v1/auth/recover", json=body)).status_code == 400
    assert (await sign_in(auth_client, account)).status_code == 401
    assert (await sign_in(auth_client, account, body["password"])).status_code == 200
    async with sessions() as s:
        events = (
            await s.scalars(select(AuditEvent).where(AuditEvent.resource_id == account.identity_id))
        ).all()
        assert any(e.action == "auth.recovered" for e in events)
        assert all(
            token not in str(e.details) and body["password"] not in str(e.details) for e in events
        )


@pytest.mark.parametrize("invalid", ["expired", "superseded", "inactive"])
async def test_recovery_expiry_replacement_and_inactive_account(
    auth_client, account, sessions, invalid
):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from app.identity.models import RecoveryToken
    from app.identity.recovery import issue_recovery

    async with sessions() as s, s.begin():
        token = await issue_recovery(s, account.email)
        if invalid == "expired":
            await s.execute(
                update(RecoveryToken)
                .where(RecoveryToken.account_id == account.id)
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        elif invalid == "superseded":
            await issue_recovery(s, account.email)
        else:
            (await s.get(Account, account.id)).active = False
    assert (
        await auth_client.post(
            "/api/v1/auth/recover",
            json={"token": token, "password": "Recovered-test-password-2026"},
        )
    ).status_code == 400


async def test_concurrent_recovery_token_use_succeeds_only_once(settings, sessions, account):
    import asyncio

    from app.identity.recovery import issue_recovery

    async with sessions() as s, s.begin():
        token = await issue_recovery(s, account.email)
    app = create_app(settings)
    async with app.router.lifespan_context(app):

        async def attempt():
            async with AsyncClient(
                transport=ASGITransport(app),
                base_url="http://test",
                headers={"origin": "http://localhost:5173"},
            ) as client:
                return (
                    await client.post(
                        "/api/v1/auth/recover",
                        json={"token": token, "password": "Recovered-test-password-2026"},
                    )
                ).status_code

        assert sorted(await asyncio.gather(attempt(), attempt())) == [200, 400]


async def test_login_audit_failure_does_not_issue_session(
    auth_client, account, monkeypatch, sessions
):
    from sqlalchemy import select

    from app.identity.models import LoginSession

    async def fail_audit(session, **kwargs):
        return await record_event(session, action="auth.signed_in", actor_id=uuid4())

    monkeypatch.setattr("app.identity.router.record_event", fail_audit)
    response = await sign_in(auth_client, account)
    assert response.status_code == 503
    assert not response.headers.get_list("set-cookie")
    async with sessions() as s:
        assert not await s.scalar(select(LoginSession).where(LoginSession.account_id == account.id))
