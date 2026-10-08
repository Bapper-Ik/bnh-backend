from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.database import Identity
from app.identity.models import Account
from app.identity.service import hasher
from app.main import create_app
from app.organisation.models import Department, Entity, Membership, Office

PASSWORD = "Synthetic-test-password-2026"


@pytest.fixture
async def organisation(sessions):
    people = {}
    async with sessions() as s, s.begin():
        entity = Entity(name=f"Synthetic company {uuid4()}")
        s.add(entity)
        await s.flush()
        department = Department(entity_id=entity.id, name="Operations")
        other_department = Department(entity_id=entity.id, name="Other department")
        s.add_all([department, other_department])
        await s.flush()
        for role in ["staff", "hod", "chief_of_staff", "md", "secretary", "chairman", "other_hod"]:
            identity = Identity(display_name=f"Synthetic {role}")
            s.add(identity)
            await s.flush()
            account = Account(
                identity_id=identity.id,
                email=f"{role}-{uuid4()}@example.com",
                password_hash=hasher.hash(PASSWORD),
                permissions=[],
            )
            s.add(account)
            s.add(
                Membership(
                    identity_id=identity.id,
                    entity_id=entity.id,
                    department_id=other_department.id if role == "other_hod" else department.id,
                )
            )
            if role != "staff":
                s.add(
                    Office(
                        identity_id=identity.id,
                        entity_id=entity.id,
                        department_id=other_department.id
                        if role == "other_hod"
                        else department.id
                        if role == "hod"
                        else None,
                        role="hod" if role == "other_hod" else role,
                        valid_from=datetime.now(UTC),
                        authorisation_reference="Synthetic test appointment",
                    )
                )
            people[role] = {
                "id": identity.id,
                "name": identity.display_name,
                "email": account.email,
            }
        return {"entity_id": str(entity.id), "people": people}


async def sign_in(client, person):
    r = await client.post(
        "/api/v1/auth/login", json={"email": person["email"], "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    client.headers["x-csrf-token"] = client.cookies.get("custodian_csrf")


def content(amount):
    return {
        "vendor": {"name": "Synthetic supplier"},
        "description": "Office materials",
        "location": "Abuja",
        "lines": [{"description": "Materials", "quantity": "1", "unit_price": amount}],
    }


async def draft(client, org, amount):
    r = await client.post(
        "/api/v1/requisitions",
        json={
            "entity_id": org["entity_id"],
            "creation_key": str(uuid4()),
            "content": content(amount),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def signed(client, req, person, action, reason=""):
    intent = {"expected_version": req["version"], "action": action, "reason": reason}
    r = await client.post(f"/api/v1/requisitions/{req['id']}/signing-challenges", json=intent)
    assert r.status_code == 201, r.text
    command = {
        **intent,
        "challenge_id": r.json()["id"],
        "idempotency_key": str(uuid4()),
        "signer_name": person["name"],
        "consent": True,
        "strokes": [[{"x": 0.1, "y": 0.2}, {"x": 0.2, "y": 0.5}, {"x": 0.4, "y": 0.3}]],
    }
    r = await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=command)
    assert r.status_code == 200, r.text
    return r.json(), command


@pytest.fixture
async def client(settings):
    app = create_app(settings)
    app.state.individual_decisions_enabled = True
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app),
            base_url="http://test",
            headers={"origin": "http://localhost:5173"},
        ) as client:
            yield client


async def test_staff_hod_approval_is_persisted_and_idempotent(client, organisation, sessions):
    people = organisation["people"]
    await sign_in(client, people["staff"])
    req = await draft(client, organisation, "5000000.00")
    req, _ = await signed(client, req, people["staff"], "submit")
    assert req["state"] == "PENDING_AUTHORITY"
    assert req["required_authority"] == "hod"
    await sign_in(client, people["other_hod"])
    assert (await client.get(f"/api/v1/requisitions/{req['id']}")).status_code == 404
    page = (await client.get("/api/v1/requisitions?inbox=true")).json()
    assert page["total"] == 0
    await sign_in(client, people["hod"])
    req, command = await signed(client, req, people["hod"], "approve")
    assert req["state"] == "APPROVED"
    replay = await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=command)
    assert replay.status_code == 200
    assert replay.json() == req
    command["reason"] = "changed intent"
    assert (
        await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=command)
    ).status_code == 409
    await sign_in(client, people["staff"])
    assert (await client.get(f"/api/v1/requisitions/{req['id']}")).json()["state"] == "APPROVED"
    with pytest.raises(DBAPIError):
        async with sessions() as s, s.begin():
            await s.execute(text("UPDATE custodian.requisition_revisions SET total=1"))


async def test_returned_request_recalculates_route_and_preserves_history(client, organisation):
    people = organisation["people"]
    await sign_in(client, people["staff"])
    req, _ = await signed(
        client, await draft(client, organisation, "4000000"), people["staff"], "submit"
    )
    await sign_in(client, people["hod"])
    req, _ = await signed(client, req, people["hod"], "return", "Please include delivery.")
    await sign_in(client, people["staff"])
    r = await client.put(
        f"/api/v1/requisitions/{req['id']}/draft",
        json={"expected_version": req["version"], "content": content("8000000")},
    )
    assert r.status_code == 200, r.text
    req, _ = await signed(client, r.json(), people["staff"], "submit")
    assert req["required_authority"] == "chief_of_staff"
    assert req["revision_number"] == 2
    assert any(event["type"] == "return" for event in req["history"])
    await sign_in(client, people["hod"])
    assert (await client.get(f"/api/v1/requisitions/{req['id']}")).status_code == 404
    await sign_in(client, people["chief_of_staff"])
    req, _ = await signed(
        client, req, people["chief_of_staff"], "reject", "Not authorised this quarter."
    )
    assert req["state"] == "REJECTED"


async def test_self_request_escalates_and_cannot_self_approve(client, organisation):
    person = organisation["people"]["hod"]
    await sign_in(client, person)
    req, _ = await signed(client, await draft(client, organisation, "1.00"), person, "submit")
    assert req["required_authority"] == "chief_of_staff"
    r = await client.post(
        f"/api/v1/requisitions/{req['id']}/signing-challenges",
        json={"expected_version": req["version"], "action": "approve"},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "SELF_APPROVAL_PROHIBITED"


async def test_signed_challenge_cannot_follow_changed_content(client, organisation):
    person = organisation["people"]["staff"]
    await sign_in(client, person)
    req = await draft(client, organisation, "10.00")
    intent = {"expected_version": req["version"], "action": "submit"}
    challenge = await client.post(
        f"/api/v1/requisitions/{req['id']}/signing-challenges", json=intent
    )
    assert challenge.status_code == 201
    assert (
        await client.put(
            f"/api/v1/requisitions/{req['id']}/draft",
            json={"expected_version": req["version"], "content": content("20.00")},
        )
    ).status_code == 200
    r = await client.post(
        f"/api/v1/requisitions/{req['id']}/actions",
        json={
            **intent,
            "challenge_id": challenge.json()["id"],
            "idempotency_key": str(uuid4()),
            "signer_name": person["name"],
            "consent": True,
            "strokes": [[{"x": 0, "y": 0}, {"x": 0.2, "y": 0.5}, {"x": 0.4, "y": 0.2}]],
        },
    )
    assert r.status_code == 409
    assert r.json()["code"] == "REVISION_CONFLICT"
