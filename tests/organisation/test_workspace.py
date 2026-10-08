import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.audit.models import AuditEvent
from app.organisation.models import Entity, Office
from tests.organisation.test_staff import signed
from tests.organisation.test_staff import staff_context as staff_context

BASE = "/api/v1/organisation/workspace"


async def workspace(c):
    r = await c["client"].get(BASE, params={"entity_id": str(c["entity"])})
    assert r.status_code == 200, r.text
    return r.json()


def company(data):
    return next(x for x in data["entities"] if x["id"] == data["selected_entity"])


async def test_workspace_scope_matrix_and_restrictions(staff_context, sessions):
    c = staff_context
    data = await workspace(c)
    assert len(data["departments"]) == 2 and data["offices"] == []
    assert {x["entity_id"] for x in data["departments"]} == {str(c["entity"])}
    assert len(data["authority_gaps"]) == 6
    assert data["matrix"][0]["authorities"] == [
        "Own department HOD",
        "Chief of Staff",
        "Managing Director",
        "Board",
    ]
    assert data["matrix"][1]["authorities"] == [
        "Chief of Staff",
        "Chief of Staff",
        "Managing Director",
        "Board",
    ]
    assert data["matrix"][2]["authorities"] == ["Managing Director"] * 3 + ["Board"]
    assert data["matrix"][3]["authorities"] == ["Board"] * 4
    assert "₦100,000,000" in data["bands"][1]
    assert (await c["client"].get(BASE, params={"entity_id": str(uuid4())})).status_code == 404
    for role in ("limited", "target"):
        async with signed(c["app"], c["people"][role]) as client:
            assert (await client.get(BASE)).status_code == 403
            assert (
                await client.patch(
                    BASE + "/entities/" + str(c["entity"]),
                    json={"expected_version": company(data)["version"], "name": "Denied"},
                )
            ).status_code == 403
    async with sessions() as s, s.begin():
        account = await s.get(type(c["people"]["target"]), c["people"]["target"].id)
        account.permissions = ["organisation:manage"]
        account.read_only = True
    async with signed(c["app"], c["people"]["target"]) as reviewer:
        assert (await reviewer.get(BASE)).status_code == 403
    assert (await c["client"].patch(BASE, json={"matrix": []})).status_code == 405


async def test_company_and_department_versions_duplicates_and_legacy_changes(staff_context):
    c = staff_context
    client = c["client"]
    data = await workspace(c)
    entity = company(data)
    path = BASE + "/entities/" + entity["id"]
    name = "Synthetic renamed " + uuid4().hex
    r = await client.patch(path, json={"expected_version": entity["version"], "name": name})
    assert r.status_code == 200 and r.json()["name"] == name
    assert r.json()["version"] != entity["version"]
    assert (
        await client.patch(path, json={"expected_version": entity["version"], "name": "Stale"})
    ).status_code == 409
    latest = r.json()
    assert (await client.patch(path, json={"name": "No version"})).status_code == 422
    assert (
        await client.patch(path, json={"expected_version": latest["version"], "code": "INJECTED"})
    ).status_code == 422
    assert (
        await client.patch(path, json={"expected_version": latest["version"]})
    ).status_code == 422
    other = await client.post(
        "/api/v1/organisation/entities", json={"name": "Synthetic duplicate " + uuid4().hex}
    )
    assert other.status_code == 201
    duplicate = await client.patch(
        path, json={"expected_version": latest["version"], "name": other.json()["name"]}
    )
    assert duplicate.status_code == 422
    assert company(await workspace(c))["name"] == name
    assert (
        await client.patch(
            "/api/v1/organisation/entities/" + entity["id"], json={"name": name + " legacy"}
        )
    ).status_code == 200
    assert (
        await client.patch(
            path, json={"expected_version": latest["version"], "name": "Stale again"}
        )
    ).status_code == 409
    dept, other_dept = data["departments"]
    path = BASE + "/departments/" + dept["id"]
    assert (
        await client.patch(
            path, json={"expected_version": dept["version"], "name": other_dept["name"]}
        )
    ).status_code == 422
    r = await client.patch(
        path, json={"expected_version": dept["version"], "name": "Updated department"}
    )
    assert r.status_code == 200 and r.json()["entity_id"] == entity["id"]
    assert (
        await client.patch(path, json={"expected_version": dept["version"], "active": False})
    ).status_code == 409


async def test_distinct_operators_race_and_origin_checks(staff_context):
    c = staff_context
    item = company(await workspace(c))
    path = BASE + "/entities/" + item["id"]
    async with signed(c["app"], c["people"]["peer"]) as peer:
        results = await asyncio.gather(
            *[
                client.patch(
                    path,
                    json={"expected_version": item["version"], "name": f"Synthetic race {uuid4()}"},
                )
                for client in (c["client"], peer)
            ]
        )
    assert sorted(r.status_code for r in results) == [200, 409]
    body = {"expected_version": company(await workspace(c))["version"], "active": False}
    assert (
        await c["client"].patch(path, json=body, headers={"origin": "https://untrusted.invalid"})
    ).status_code == 403
    assert (
        await c["client"].patch(path, json=body, headers={"x-csrf-token": ""})
    ).status_code == 403


async def test_disabled_company_prevents_new_department_and_department_enable(staff_context):
    c = staff_context
    entity = company(await workspace(c))
    path = BASE + "/entities/" + entity["id"]
    r = await c["client"].patch(path, json={"expected_version": entity["version"], "active": False})
    assert r.status_code == 200 and not r.json()["active"]
    assert (
        await c["client"].post(
            "/api/v1/organisation/departments",
            json={"entity_id": entity["id"], "name": "Must not create"},
        )
    ).status_code == 422
    dept = (await workspace(c))["departments"][0]
    dp = BASE + "/departments/" + dept["id"]
    disabled = await c["client"].patch(
        dp, json={"expected_version": dept["version"], "active": False}
    )
    assert disabled.status_code == 200
    assert (
        await c["client"].patch(
            dp, json={"expected_version": disabled.json()["version"], "active": True}
        )
    ).status_code == 422
    assert (
        await c["client"].patch(
            path, json={"expected_version": r.json()["version"], "active": True}
        )
    ).status_code == 200
    assert (
        await c["client"].patch(
            dp, json={"expected_version": disabled.json()["version"], "active": True}
        )
    ).status_code == 200


async def test_officeholder_effective_dates_scope_and_retained_history(staff_context, sessions):
    c = staff_context
    now = datetime.now(UTC)
    async with sessions() as s, s.begin():
        appointments = []
        for role, active, start, end in [
            ("hod", True, now - timedelta(days=1), None),
            ("md", True, now + timedelta(days=1), None),
            ("chief_of_staff", True, now - timedelta(days=2), now - timedelta(days=1)),
            ("secretary", False, now - timedelta(days=1), None),
        ]:
            office = Office(
                identity_id=c["people"]["target"].identity_id,
                entity_id=c["entity"],
                department_id=c["departments"][0].id if role == "hod" else None,
                role=role,
                active=active,
                valid_from=start,
                valid_until=end,
                authorisation_reference="Synthetic approved office",
            )
            s.add(office)
            appointments.append(office)
    data = await workspace(c)
    statuses = {x["role"]: x["status"] for x in data["offices"]}
    assert statuses == {
        "hod": "active",
        "md": "scheduled",
        "chief_of_staff": "expired",
        "secretary": "revoked",
    }
    assert all(
        x["holder_name"] and "password" not in str(x) and "email" not in x for x in data["offices"]
    )
    dept = next(d for d in data["departments"] if d["id"] == str(c["departments"][0].id))
    dp = BASE + "/departments/" + dept["id"]
    disabled = await c["client"].patch(
        dp, json={"expected_version": dept["version"], "active": False}
    )
    assert disabled.status_code == 200
    assert (
        next(o for o in (await workspace(c))["offices"] if o["role"] == "hod")["status"]
        == "blocked"
    )
    assert (
        await c["client"].patch(
            dp, json={"expected_version": disabled.json()["version"], "active": True}
        )
    ).status_code == 200
    target = (await c["client"].get(f"/api/v1/staff/{c['people']['target'].identity_id}")).json()
    assert (
        await c["client"].post(
            f"/api/v1/staff/{target['id']}/state",
            json={"expected_version": target["version"], "active": False},
        )
    ).status_code == 200
    statuses = {x["role"]: x["status"] for x in (await workspace(c))["offices"]}
    assert statuses["hod"] == "blocked" and statuses["md"] == "blocked"
    assert statuses["secretary"] == "revoked" and statuses["chief_of_staff"] == "expired"
    entity = company(await workspace(c))
    assert (
        await c["client"].patch(
            BASE + "/entities/" + entity["id"],
            json={"expected_version": entity["version"], "active": False},
        )
    ).status_code == 200
    assert len((await workspace(c))["offices"]) == 4
    async with sessions() as s:
        assert (await s.get(Office, appointments[0].id)).active
        assert await s.scalar(
            select(AuditEvent.id).where(AuditEvent.resource_id == UUID(entity["id"]))
        )


async def test_organisation_audit_failure_rolls_back(staff_context, monkeypatch, sessions):
    c = staff_context
    item = company(await workspace(c))

    async def fail(*args, **kwargs):
        raise SQLAlchemyError("Synthetic mandatory audit failure")

    monkeypatch.setattr("app.organisation.lifecycle.record_event", fail)
    r = await c["client"].patch(
        BASE + "/entities/" + item["id"],
        json={"expected_version": item["version"], "active": False},
    )
    assert r.status_code == 503
    async with sessions() as s:
        assert (await s.get(Entity, UUID(item["id"]))).active


async def test_duplicate_active_officeholder_is_rejected_and_existing_holder_retained(
    staff_context, sessions
):
    c = staff_context

    def office():
        return Office(
            identity_id=c["people"]["target"].identity_id,
            entity_id=c["entity"],
            department_id=c["departments"][0].id,
            role="hod",
            active=True,
            valid_from=datetime.now(UTC) - timedelta(days=1),
            valid_until=None,
            authorisation_reference="Synthetic approved appointment",
        )

    async with sessions() as s, s.begin():
        s.add(office())
    with pytest.raises(IntegrityError):
        async with sessions() as s, s.begin():
            s.add(office())
    data = await workspace(c)
    assert len(data["offices"]) == 1
    assert data["offices"][0]["status"] == "active"
    assert not any("conflicting current appointments" in gap for gap in data["authority_gaps"])
