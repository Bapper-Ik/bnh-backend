from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import Identity
from app.core.errors import DomainError
from app.identity.models import Account
from app.identity.service import hasher
from app.org_app import create_app
from app.organisation.models import Department, Membership, Office
from app.organisation.service import membership, officeholder

PASSWORD = "Synthetic-organisation-password"


@pytest.fixture
async def directory(settings, sessions):
    async with sessions() as s, s.begin():
        person = Identity(display_name="Synthetic configuration operator")
        s.add(person)
        await s.flush()
        admin = Account(
            identity_id=person.id,
            email=f"{uuid4()}@example.com",
            password_hash=hasher.hash(PASSWORD),
            permissions=["staff:manage", "organisation:manage", "office_assignment:manage"],
        )
        s.add(admin)
        await s.flush()
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app),
            base_url="http://test",
            headers={"origin": "http://localhost:5173"},
        ) as client:
            assert (
                await client.post(
                    "/api/v1/auth/login", json={"email": admin.email, "password": PASSWORD}
                )
            ).status_code == 200
            client.headers["x-csrf-token"] = client.cookies.get("custodian_csrf")
            company = await client.post(
                "/api/v1/organisation/entities",
                json={"name": f"Synthetic company {uuid4()}", "kind": "holding"},
            )
            assert company.status_code == 201, company.text
            entity = company.json()["id"]
            departments, staff = [], []
            for index in range(2):
                department = await client.post(
                    "/api/v1/organisation/departments",
                    json={"entity_id": entity, "name": f"Department {index}"},
                )
                assert department.status_code == 201, department.text
                departments.append(department.json()["id"])
                response = await client.post(
                    "/api/v1/auth/accounts",
                    json={
                        "name": f"Synthetic staff {index}",
                        "email": f"{uuid4()}@example.com",
                        "initial_password": PASSWORD,
                    },
                )
                assert response.status_code == 201, response.text
                staff.append(response.json())
                assert (
                    await client.post(
                        "/api/v1/organisation/memberships",
                        json={
                            "identity_id": staff[-1]["id"],
                            "entity_id": entity,
                            "department_id": departments[-1],
                        },
                    )
                ).status_code == 201
            yield {
                "client": client,
                "app": app,
                "entity": entity,
                "departments": departments,
                "staff": staff,
                "admin": admin,
            }


def appointment(directory, index=0, role="hod", **overrides):
    return {
        "identity_id": directory["staff"][index]["id"],
        "entity_id": directory["entity"],
        "department_id": directory["departments"][index] if role == "hod" else None,
        "role": role,
        "authorisation_reference": "Synthetic approved appointment",
        **overrides,
    }


async def test_department_heads_resolve_only_in_their_department(directory, sessions):
    client = directory["client"]
    for index in range(2):
        response = await client.post(
            "/api/v1/organisation/offices", json=appointment(directory, index)
        )
        assert response.status_code == 201, response.text
    async with sessions() as s, s.begin():
        for index in range(2):
            holder = await officeholder(
                s, UUID(directory["entity"]), "hod", UUID(directory["departments"][index])
            )
            assert str(holder.identity_id) == directory["staff"][index]["id"]
        with pytest.raises(DomainError):
            await officeholder(s, uuid4(), "hod", UUID(directory["departments"][0]))


async def test_invalid_scope_self_grants_and_mass_assignment_are_rejected(directory):
    client = directory["client"]
    wrong = appointment(directory, department_id=directory["departments"][1])
    assert (await client.post("/api/v1/organisation/offices", json=wrong)).status_code == 422
    own = appointment(directory, identity_id=str(directory["admin"].identity_id))
    assert (await client.post("/api/v1/organisation/offices", json=own)).status_code == 403
    assert (
        await client.patch(
            f"/api/v1/organisation/staff/{directory['admin'].identity_id}",
            json={"role": "md", "permissions": ["office_assignment:manage"]},
        )
    ).status_code == 422
    assert (
        await client.post(
            "/api/v1/organisation/memberships",
            json={
                "identity_id": directory["staff"][0]["id"],
                "entity_id": str(uuid4()),
                "department_id": directory["departments"][0],
            },
        )
    ).status_code == 422


async def test_board_roles_must_be_different_people(directory):
    client = directory["client"]
    assert (
        await client.post(
            "/api/v1/organisation/offices", json=appointment(directory, role="secretary")
        )
    ).status_code == 201
    response = await client.post(
        "/api/v1/organisation/offices", json=appointment(directory, role="chairman")
    )
    assert response.status_code == 409
    assert response.json()["code"] == "AUTHORITY_ASSIGNMENT_BLOCKED"
    assert (
        await client.post(
            "/api/v1/organisation/offices", json=appointment(directory, 1, role="chairman")
        )
    ).status_code == 201


async def test_expired_future_and_invalid_appointment_dates(directory, sessions):
    client = directory["client"]
    start = datetime.now(UTC) + timedelta(days=1)
    body = appointment(
        directory, valid_from=start.isoformat(), valid_until=(start + timedelta(days=1)).isoformat()
    )
    assert (await client.post("/api/v1/organisation/offices", json=body)).status_code == 201
    async with sessions() as s, s.begin():
        with pytest.raises(DomainError):
            await officeholder(
                s, UUID(directory["entity"]), "hod", UUID(directory["departments"][0])
            )
    response = await client.post(
        "/api/v1/organisation/offices",
        json=appointment(directory, 1, valid_from=start.isoformat(), valid_until=start.isoformat()),
    )
    assert response.status_code == 422
    response = await client.post(
        "/api/v1/organisation/offices",
        json=appointment(directory, 1, valid_from="2026-10-01T00:00:00"),
    )
    assert response.status_code == 422


async def test_transfer_requires_revocation_and_preserves_prior_appointment(directory, sessions):
    client = directory["client"]
    old = await client.post("/api/v1/organisation/offices", json=appointment(directory))
    assert old.status_code == 201
    body = {
        "identity_id": directory["staff"][0]["id"],
        "entity_id": directory["entity"],
        "department_id": directory["departments"][1],
    }
    assert (await client.post("/api/v1/organisation/memberships", json=body)).status_code == 409
    assert (
        await client.post(f"/api/v1/organisation/offices/{old.json()['id']}/revoke")
    ).status_code == 200
    assert (await client.post("/api/v1/organisation/memberships", json=body)).status_code == 201
    async with sessions() as s:
        history = await s.get(Office, UUID(old.json()["id"]))
        assert str(history.department_id) == directory["departments"][0]
        assert history.active is False
        current = await s.scalar(
            select(Membership).where(Membership.identity_id == UUID(body["identity_id"]))
        )
        assert str(current.department_id) == body["department_id"]


@pytest.mark.parametrize("scope", ["staff", "department", "entity", "membership"])
async def test_deactivation_removes_current_authority(directory, sessions, scope):
    client = directory["client"]
    assert (
        await client.post("/api/v1/organisation/offices", json=appointment(directory))
    ).status_code == 201
    paths = {
        "staff": f"/staff/{directory['staff'][0]['id']}",
        "department": f"/departments/{directory['departments'][0]}",
        "entity": f"/entities/{directory['entity']}",
        "membership": f"/memberships/{directory['staff'][0]['id']}/{directory['entity']}",
    }
    assert (
        await client.patch("/api/v1/organisation" + paths[scope], json={"active": False})
    ).status_code == 200
    async with sessions() as s, s.begin():
        with pytest.raises(DomainError):
            await officeholder(
                s, UUID(directory["entity"]), "hod", UUID(directory["departments"][0])
            )
        if scope != "staff":
            with pytest.raises(DomainError):
                await membership(s, UUID(directory["staff"][0]["id"]), UUID(directory["entity"]))


async def test_deactivated_staff_cannot_use_old_session(directory):
    async with AsyncClient(
        transport=ASGITransport(directory["app"]),
        base_url="http://test",
        headers={"origin": "http://localhost:5173"},
    ) as staff:
        assert (
            await staff.post(
                "/api/v1/auth/login",
                json={"email": directory["staff"][0]["email"], "password": PASSWORD},
            )
        ).status_code == 200
        csrf = staff.cookies.get("custodian_csrf")
        assert (
            await directory["client"].patch(
                f"/api/v1/organisation/staff/{directory['staff'][0]['id']}", json={"active": False}
            )
        ).status_code == 200
        assert (
            await staff.post(
                "/api/v1/auth/reauthenticate",
                json={"password": PASSWORD},
                headers={"x-csrf-token": csrf},
            )
        ).status_code == 401


async def test_account_manager_cannot_grant_appointments(directory, sessions):
    async with sessions() as s, s.begin():
        (await s.get(Account, directory["admin"].id)).permissions = ["staff:manage"]
    assert (
        await directory["client"].post("/api/v1/organisation/offices", json=appointment(directory))
    ).status_code == 403


async def test_concurrent_executive_appointments_have_one_winner(directory):
    import asyncio

    # Separate operator sessions share the authoritative account lock; the scope
    # advisory lock additionally serialises separate operators in production.
    responses = await asyncio.gather(
        *(
            directory["client"].post(
                "/api/v1/organisation/offices", json=appointment(directory, index, role="md")
            )
            for index in range(2)
        )
    )
    assert sorted(r.status_code for r in responses) == [201, 409]


async def test_rejected_office_assignment_has_safe_failure_audit(directory, sessions):
    from app.audit.models import AuditEvent

    response = await directory["client"].post(
        "/api/v1/organisation/offices",
        json=appointment(directory, identity_id=str(directory["admin"].identity_id)),
    )
    assert response.status_code == 403
    async with sessions() as s:
        event = await s.scalar(
            select(AuditEvent).where(
                AuditEvent.correlation_id == UUID(response.headers["x-request-id"])
            )
        )
        assert event.action == "office.assignment_failed"
        assert event.actor_id == directory["admin"].identity_id
        assert event.details["outcome"] == "denied"
        assert "Synthetic approved appointment" not in str(event.details)


async def test_expired_appointment_cannot_resolve(directory, sessions):
    start = datetime.now(UTC) - timedelta(days=2)
    response = await directory["client"].post(
        "/api/v1/organisation/offices",
        json=appointment(
            directory,
            valid_from=start.isoformat(),
            valid_until=(start + timedelta(days=1)).isoformat(),
        ),
    )
    assert response.status_code == 201
    async with sessions() as s, s.begin():
        with pytest.raises(DomainError):
            await officeholder(
                s, UUID(directory["entity"]), "hod", UUID(directory["departments"][0])
            )


async def test_directory_changes_preserve_frozen_request_history(directory, sessions):
    from sqlalchemy import text

    # Insert a synthetic frozen revision using the already-applied schema. This
    # proves the organisation feature's history contract independently of the
    # later requisition API, which is not part of this feature commit.
    req_id, revision_id = uuid4(), uuid4()
    staff_id = UUID(directory["staff"][0]["id"])
    department_id, entity_id = UUID(directory["departments"][0]), UUID(directory["entity"])
    async with sessions() as s, s.begin():
        await s.execute(
            text("""INSERT INTO custodian.requisitions (id,reference,requester_id,entity_id,department_id,creation_key,creation_digest,state,version,content,total,revision_number)
            VALUES (:id,:reference,:staff,:entity,:department,:key,'synthetic','PENDING_AUTHORITY',1,'{}',1,1)"""),
            {
                "id": req_id,
                "reference": f"SYNTHETIC-{req_id}",
                "staff": staff_id,
                "entity": entity_id,
                "department": department_id,
                "key": uuid4(),
            },
        )
        await s.execute(
            text("""INSERT INTO custodian.requisition_revisions (id,requisition_id,number,content,total,requester_name,department_name,entity_name,authority,approver_id,policy_version,routing_explanation,content_digest,signature)
            VALUES (:id,:request,1,'{}',1,'Original staff','Original department','Original company','hod',:approver,'bnh-doa-v1','Synthetic office snapshot','synthetic','{}')"""),
            {"id": revision_id, "request": req_id, "approver": UUID(directory["staff"][1]["id"])},
        )
    client = directory["client"]
    assert (
        await client.patch(f"/api/v1/organisation/staff/{staff_id}", json={"name": "Updated staff"})
    ).status_code == 200
    assert (
        await client.patch(
            f"/api/v1/organisation/departments/{department_id}", json={"name": "Updated department"}
        )
    ).status_code == 200
    assert (
        await client.post(
            "/api/v1/organisation/memberships",
            json={
                "identity_id": str(staff_id),
                "entity_id": str(entity_id),
                "department_id": directory["departments"][1],
            },
        )
    ).status_code == 201
    async with sessions() as s:
        snapshot = (
            await s.execute(
                text(
                    "SELECT requester_name,department_name,entity_name,approver_id FROM custodian.requisition_revisions WHERE id=:id"
                ),
                {"id": revision_id},
            )
        ).one()
        assert tuple(snapshot) == (
            "Original staff",
            "Original department",
            "Original company",
            UUID(directory["staff"][1]["id"]),
        )
        assert await s.get(Department, department_id)


async def test_two_operators_cannot_create_ambiguous_office(directory, sessions):
    import asyncio

    async with sessions() as s, s.begin():
        person = Identity(display_name="Second synthetic configuration operator")
        s.add(person)
        await s.flush()
        operator = Account(
            identity_id=person.id,
            email=f"{uuid4()}@example.com",
            password_hash=hasher.hash(PASSWORD),
            permissions=["office_assignment:manage"],
        )
        s.add(operator)
        await s.flush()
    async with AsyncClient(
        transport=ASGITransport(directory["app"]),
        base_url="http://test",
        headers={"origin": "http://localhost:5173"},
    ) as second:
        assert (
            await second.post(
                "/api/v1/auth/login", json={"email": operator.email, "password": PASSWORD}
            )
        ).status_code == 200
        second.headers["x-csrf-token"] = second.cookies.get("custodian_csrf")
        responses = await asyncio.gather(
            directory["client"].post(
                "/api/v1/organisation/offices", json=appointment(directory, role="md")
            ),
            second.post("/api/v1/organisation/offices", json=appointment(directory, 1, role="md")),
        )
        assert sorted(r.status_code for r in responses) == [201, 409]
