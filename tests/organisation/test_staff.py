import asyncio
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.audit.models import AuditEvent
from app.core.database import Identity
from app.identity.email_delivery import link_token
from app.identity.models import Account, RecoveryToken
from app.identity.service import hasher
from app.organisation.models import Department, Entity, Membership
from app.vendor_app import create_app

PASSWORD = "Synthetic-staff-management-password"
PERMISSIONS = ["staff:manage", "organisation:manage", "office_assignment:manage"]


@asynccontextmanager
async def signed(app, account):
    async with AsyncClient(
        transport=ASGITransport(app),
        base_url="http://test",
        headers={"origin": "http://localhost:5173"},
    ) as client:
        assert (
            await client.post(
                "/api/v1/auth/login", json={"email": account.email, "password": PASSWORD}
            )
        ).status_code == 200
        client.headers["x-csrf-token"] = client.cookies.get("custodian_csrf")
        yield client


@pytest.fixture
async def staff_context(settings, sessions):
    prefix = "Synthetic staff " + uuid4().hex
    people = {}
    async with sessions() as s, s.begin():
        entity = Entity(name=prefix)
        s.add(entity)
        await s.flush()
        departments = [
            Department(entity_id=entity.id, name="Operations"),
            Department(entity_id=entity.id, name="Support"),
        ]
        s.add_all(departments)
        await s.flush()
        for role in ("admin", "peer", "limited", "target", "other"):
            person = Identity(display_name=prefix + " " + role)
            s.add(person)
            await s.flush()
            account = Account(
                identity_id=person.id,
                email=f"{uuid4()}@example.com",
                password_hash=hasher.hash(PASSWORD),
                permissions=PERMISSIONS
                if role in {"admin", "peer"}
                else ["staff:manage"]
                if role == "limited"
                else [],
            )
            s.add(account)
            people[role] = account
        await s.flush()
        s.add(
            Membership(
                identity_id=people["target"].identity_id,
                entity_id=entity.id,
                department_id=departments[0].id,
            )
        )
    config = settings.model_copy(
        update={
            "mail_enabled": True,
            "mail_from": "synthetic@example.com",
            "resend_api_key": SecretStr("synthetic-key"),
            "account_link_secret": SecretStr(uuid4().hex + uuid4().hex),
            "frontend_origin": "http://localhost:5173",
        }
    )
    app = create_app(config)
    app.state.account_email_worker = False
    async with app.router.lifespan_context(app), signed(app, people["admin"]) as client:
        yield {
            "app": app,
            "client": client,
            "people": people,
            "entity": entity.id,
            "departments": departments,
            "prefix": prefix,
            "settings": config,
        }


async def view(context, role="target"):
    response = await context["client"].get(f"/api/v1/staff/{context['people'][role].identity_id}")
    assert response.status_code == 200
    return response.json()


def route(context, action="", role="target"):
    return f"/api/v1/staff/{context['people'][role].identity_id}" + action


async def test_staff_search_pagination_filter_and_no_credentials(staff_context):
    c = staff_context
    client = c["client"]
    response = await client.get("/api/v1/staff", params={"search": c["prefix"], "limit": 2})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 5 and len(data["items"]) == 2
    next_page = (
        await client.get("/api/v1/staff", params={"search": c["prefix"], "limit": 2, "offset": 2})
    ).json()
    assert not {x["id"] for x in data["items"]} & {x["id"] for x in next_page["items"]}
    assert (await client.get("/api/v1/staff", params={"search": c["prefix"] + "%"})).json()[
        "total"
    ] == 0
    detail = await view(c)
    assert set(detail) == {
        "id",
        "name",
        "email",
        "status",
        "read_only",
        "version",
        "memberships",
        "offices",
        "actions",
    }
    assert "password" not in response.text and "token" not in response.text
    assert (await client.get("/api/v1/staff?status=unknown")).status_code == 422


async def test_staff_capability_and_origin_boundaries(staff_context):
    c = staff_context
    async with signed(c["app"], c["people"]["target"]) as normal:
        for path in ("/api/v1/staff", route(c), "/api/v1/staff/options"):
            assert (await normal.get(path)).status_code == 403
    async with signed(c["app"], c["people"]["limited"]) as limited:
        assert (await limited.get("/api/v1/staff/options")).json()["entities"] == []
        data = (await limited.get(route(c))).json()
        assert "assign_office" not in data["actions"] and "set_membership" not in data["actions"]
        payload = {
            "identity_id": data["id"],
            "entity_id": str(c["entity"]),
            "department_id": str(c["departments"][0].id),
            "expected_version": data["version"],
        }
        assert (await limited.post(route(c, "/memberships"), json=payload)).status_code == 403
    data = await view(c)
    for headers in ({"origin": "https://untrusted.example"}, {"x-csrf-token": "wrong"}):
        assert (
            await c["client"].patch(
                route(c),
                json={"expected_version": data["version"], "name": "Should not save"},
                headers=headers,
            )
        ).status_code == 403


async def test_self_status_and_protected_field_changes_are_denied(staff_context):
    c = staff_context
    current = await view(c, "admin")
    assert "disable" not in current["actions"] and "assign_office" not in current["actions"]
    assert (
        await c["client"].post(
            route(c, "/state", "admin"),
            json={"expected_version": current["version"], "active": False},
        )
    ).status_code == 403
    assert (
        await c["client"].patch(
            f"/api/v1/organisation/staff/{current['id']}", json={"active": False}
        )
    ).status_code == 403
    current = await view(c)
    assert (
        await c["client"].patch(
            route(c),
            json={
                "expected_version": current["version"],
                "name": "Changed",
                "permissions": PERMISSIONS,
            },
        )
    ).status_code == 422
    assert (await c["client"].patch(route(c), json={"name": "No version"})).status_code == 422


async def test_stale_edit_and_concurrent_operators_have_one_winner(staff_context, sessions):
    c = staff_context
    current = await view(c)
    async with signed(c["app"], c["people"]["peer"]) as peer:
        results = await asyncio.gather(
            c["client"].patch(
                route(c), json={"expected_version": current["version"], "name": "First edit"}
            ),
            peer.patch(
                route(c), json={"expected_version": current["version"], "name": "Second edit"}
            ),
        )
    assert sorted(r.status_code for r in results) == [200, 409]
    async with sessions() as s:
        events = (
            await s.scalars(
                select(AuditEvent).where(
                    AuditEvent.resource_id == UUID(current["id"]),
                    AuditEvent.action == "identity.updated",
                )
            )
        ).all()
        assert len(events) == 1
    current = await view(c)
    await c["client"].patch(
        f"/api/v1/organisation/staff/{current['id']}", json={"name": "Legacy edit"}
    )
    assert (
        await c["client"].patch(
            route(c), json={"expected_version": current["version"], "name": "Stale new edit"}
        )
    ).status_code == 409


async def test_disable_enable_and_session_revocation(staff_context):
    c = staff_context
    async with signed(c["app"], c["people"]["target"]) as target:
        current = await view(c)
        response = await c["client"].post(
            route(c, "/state"), json={"expected_version": current["version"], "active": False}
        )
        assert response.status_code == 200 and response.json()["status"] == "disabled"
        assert (await target.get("/api/v1/auth/me")).status_code == 401
        assert (
            await c["client"].get(
                "/api/v1/staff",
                params={"search": c["people"]["target"].email, "status": "disabled"},
            )
        ).json()["total"] == 1
        enabled = await c["client"].post(
            route(c, "/state"),
            json={"expected_version": response.json()["version"], "active": True},
        )
        assert enabled.status_code == 200
        assert (await target.get("/api/v1/auth/me")).status_code == 401
    async with signed(c["app"], c["people"]["target"]) as target:
        current = await view(c)
        assert (
            await c["client"].post(
                route(c, "/revoke-sessions"), json={"expected_version": current["version"]}
            )
        ).status_code == 200
        assert (await target.get("/api/v1/auth/me")).status_code == 401


async def test_membership_office_assignment_conflicts_and_revocation(staff_context):
    c = staff_context
    client = c["client"]
    current = await view(c)
    office = {
        "identity_id": current["id"],
        "entity_id": str(c["entity"]),
        "department_id": str(c["departments"][0].id),
        "role": "hod",
        "authorisation_reference": "Synthetic BNH appointment",
        "expected_version": current["version"],
    }
    result = await client.post(route(c, "/offices"), json=office)
    assert result.status_code == 200, result.text
    current = result.json()
    office_id = current["offices"][0]["id"]
    transfer = {
        "identity_id": current["id"],
        "entity_id": str(c["entity"]),
        "department_id": str(c["departments"][1].id),
        "expected_version": current["version"],
    }
    assert (await client.post(route(c, "/memberships"), json=transfer)).status_code == 409
    other = await view(c, "other")
    assert (
        await client.post(
            route(c, f"/offices/{office_id}/revoke", "other"),
            json={"expected_version": other["version"]},
        )
    ).status_code == 404
    result = await client.post(
        route(c, f"/offices/{office_id}/revoke"), json={"expected_version": current["version"]}
    )
    assert result.status_code == 200 and result.json()["offices"][0]["active"] is False
    transfer["expected_version"] = result.json()["version"]
    result = await client.post(route(c, "/memberships"), json=transfer)
    assert (
        result.status_code == 200
        and result.json()["memberships"][0]["department_name"] == "Support"
    )
    result = await client.post(
        route(c, f"/memberships/{c['entity']}/state"),
        json={"expected_version": result.json()["version"], "active": False},
    )
    assert result.status_code == 200 and not result.json()["memberships"][0]["active"]


async def test_invitation_resend_activation_and_pending_authority(staff_context, sessions):
    c = staff_context
    client = c["client"]
    response = await client.post(
        "/api/v1/auth/invitations",
        json={"name": "Synthetic invited colleague", "email": f"{uuid4()}@example.com"},
    )
    assert response.status_code == 201
    identity = response.json()["identity_id"]
    current = (await client.get(f"/api/v1/staff/{identity}")).json()
    assert current["status"] == "invited" and "assign_office" not in current["actions"]
    result = await client.post(
        f"/api/v1/staff/{identity}/invitation", json={"expected_version": current["version"]}
    )
    assert result.status_code == 200 and result.json()["version"] != current["version"]
    async with sessions() as s:
        token = await s.scalar(
            select(RecoveryToken)
            .join(Account)
            .where(Account.identity_id == UUID(identity), RecoveryToken.consumed_at.is_(None))
        )
        raw = link_token(c["settings"], token.id)
    assert (
        await client.post("/api/v1/auth/recover", json={"token": raw, "password": PASSWORD})
    ).status_code == 200
    # Redeeming a token clears this browser's cookies; sign in as operator again.
    async with signed(c["app"], c["people"]["admin"]) as admin:
        current = (await admin.get(f"/api/v1/staff/{identity}")).json()
        assert (
            current["status"] == "active"
            and current["memberships"] == []
            and current["offices"] == []
        )
        assert (
            await admin.post(
                f"/api/v1/staff/{identity}/invitation",
                json={"expected_version": current["version"]},
            )
        ).status_code == 409


async def test_audit_failure_rolls_back_staff_edit(staff_context, monkeypatch):
    c = staff_context
    current = await view(c)

    async def fail(*args, **kwargs):
        raise SQLAlchemyError("Synthetic audit failure")

    monkeypatch.setattr("app.organisation.lifecycle.record_event", fail)
    response = await c["client"].patch(
        route(c), json={"expected_version": current["version"], "name": "Must roll back"}
    )
    assert response.status_code == 503
    assert (await view(c))["name"] == current["name"]
