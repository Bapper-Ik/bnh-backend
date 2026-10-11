import asyncio
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.organisation.models import Department
from tests.organisation.test_staff import signed
from tests.organisation.test_staff import staff_context as staff_context
from tests.organisation.test_workspace import BASE, workspace


async def test_department_codes_are_admin_selected_validated_and_unique(staff_context):
    c = staff_context
    client = c["client"]
    body = {"entity_id": str(c["entity"]), "name": "Finance " + uuid4().hex, "code": "fin"}
    result = await client.post("/api/v1/organisation/departments", json=body)
    assert result.status_code == 201, result.text
    assert result.json()["code"] == "FIN"
    duplicate = await client.post(
        "/api/v1/organisation/departments", json={**body, "name": "Duplicate", "code": "FIN"}
    )
    assert duplicate.status_code == 422
    for code in ["FI", "FINA", "F1N", "F-N", "F_N", "F N", "FÍN", "ßa"]:
        invalid = await client.post("/api/v1/organisation/departments", json={**body, "code": code})
        assert invalid.status_code == 422, code
    assert (
        await client.post(
            "/api/v1/organisation/departments",
            json={"entity_id": str(c["entity"]), "name": "Missing"},
        )
    ).status_code == 422
    async with signed(c["app"], c["people"]["target"]) as requester:
        assert (
            await requester.post("/api/v1/organisation/departments", json=body)
        ).status_code == 403


async def test_department_code_edits_require_current_version_and_permission(staff_context):
    c = staff_context
    dept = (await workspace(c))["departments"][0]
    path = BASE + "/departments/" + dept["id"]
    body = {"expected_version": dept["version"], "code": "adm"}
    async with signed(c["app"], c["people"]["target"]) as requester:
        assert (await requester.patch(path, json=body)).status_code == 403
    changed = await c["client"].patch(path, json=body)
    assert changed.status_code == 200, changed.text
    assert changed.json()["code"] == "ADM" and changed.json()["version"] != dept["version"]
    assert (await c["client"].patch(path, json={**body, "code": "ICT"})).status_code == 409
    legacy = "/api/v1/organisation/departments/" + dept["id"]
    assert (await c["client"].patch(legacy, json={"code": "ICT"})).status_code == 422
    changed_again = await c["client"].patch(
        legacy, json={"code": "ict", "expected_version": changed.json()["version"]}
    )
    assert changed_again.status_code == 200 and changed_again.json()["code"] == "ICT"


async def test_competing_department_codes_do_not_duplicate(staff_context):
    c = staff_context
    departments = (await workspace(c))["departments"]
    results = await asyncio.gather(
        *[
            c["client"].patch(
                BASE + "/departments/" + dept["id"],
                json={"expected_version": dept["version"], "code": "FIN"},
            )
            for dept in departments
        ]
    )
    assert sorted(r.status_code for r in results) == [200, 422]
    assert sum(d["code"] == "FIN" for d in (await workspace(c))["departments"]) == 1


async def test_department_code_audit_failure_rolls_back(staff_context, monkeypatch, sessions):
    c = staff_context
    dept = (await workspace(c))["departments"][0]

    async def fail(*args, **kwargs):
        raise SQLAlchemyError("Synthetic audit failure")

    monkeypatch.setattr("app.organisation.lifecycle.record_event", fail)
    response = await c["client"].patch(
        BASE + "/departments/" + dept["id"],
        json={"expected_version": dept["version"], "code": "FIN"},
    )
    assert response.status_code == 503
    async with sessions() as s:
        assert (
            await s.scalar(select(Department.code).where(Department.id == dept["id"]))
            == dept["code"]
        )
