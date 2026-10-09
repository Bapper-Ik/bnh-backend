from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.access.roles import SYSTEM_ADMIN_PERMISSIONS
from app.core.database import Identity
from app.identity.models import Account
from app.identity.service import hasher
from app.organisation.models import Department, Entity, Membership
from tests.requisitions.test_creation import context as context
from tests.requisitions.test_creation import upload
from tests.requisitions.test_workflow import PASSWORD, content, draft, sign_in, signed
from tests.requisitions.test_workflow import organisation as organisation
from tests.vendors.test_vendors import data as vendor_data


@pytest.fixture
async def administrator(sessions):
    async with sessions() as s, s.begin():
        person = Identity(display_name="Synthetic oversight administrator")
        s.add(person)
        await s.flush()
        account = Account(
            identity_id=person.id,
            email=f"{uuid4()}@example.com",
            password_hash=hasher.hash(PASSWORD),
            permissions=sorted(SYSTEM_ADMIN_PERMISSIONS),
        )
        s.add(account)
        await s.flush()
        return {
            "id": person.id,
            "email": account.email,
            "name": person.display_name,
            "account_id": account.id,
        }


async def test_full_admin_without_membership_sees_cross_company_drafts_and_counts(
    context, organisation, administrator, sessions
):
    c = context[0]
    people = organisation["people"]
    await sign_in(c, people["staff"])
    first = await draft(c, organisation, "24")
    async with sessions() as s, s.begin():
        entity = Entity(name="Synthetic oversight second " + str(uuid4()))
        s.add(entity)
        await s.flush()
        dept = Department(entity_id=entity.id, name="Second department")
        s.add(dept)
        await s.flush()
        s.add(
            Membership(
                identity_id=people["other_hod"]["id"], entity_id=entity.id, department_id=dept.id
            )
        )
    await sign_in(c, people["other_hod"])
    second = await draft(c, {"entity_id": str(entity.id)}, "48")
    await sign_in(c, administrator)
    me = (await c.get("/api/v1/auth/me")).json()
    assert (
        me["is_system_administrator"]
        and not me["can_create_requisitions"]
        and not me["can_access_approval_inbox"]
    )
    assert (await c.get("/api/v1/organisation/memberships")).json() == []
    for req in (first, second):
        page = (
            await c.get("/api/v1/requisitions", params={"search": req["reference"], "limit": 1})
        ).json()
        assert page["total"] == 1 and page["items"][0]["id"] == req["id"]
        view = (await c.get("/api/v1/requisitions/" + req["id"])).json()
        assert view["oversight_only"] and view["available_actions"] == []
        caps = (await c.get("/api/v1/access/requisitions/" + req["id"])).json()
        assert caps["read_only"] and caps["actions"] == ["read"]
    filtered = (await c.get("/api/v1/requisitions", params={"company": entity.name})).json()
    assert filtered["total"] == 1
    dash = (await c.get("/api/v1/dashboard")).json()
    assert dash["total"] == (await c.get("/api/v1/requisitions")).json()["total"]
    assert not dash["can_create"] and dash["tasks"]["total"] == 0
    assert (await c.get("/api/v1/approvals/inbox")).json()["total"] == 0
    assert (
        await c.post(
            "/api/v1/requisitions",
            json={
                "entity_id": organisation["entity_id"],
                "creation_key": str(uuid4()),
                "content": {},
            },
        )
    ).status_code == 403
    assert (
        await c.put(
            "/api/v1/requisitions/" + first["id"] + "/draft",
            json={"expected_version": first["version"], "content": content("12")},
        )
    ).status_code == 403
    async with sessions() as s, s.begin():
        (await s.get(Entity, entity.id)).active = False
    assert (await c.get("/api/v1/requisitions/" + second["id"])).status_code == 200


async def test_admin_reads_redacted_current_and_signed_versions_without_files_or_decisions(
    context, organisation, administrator, sessions
):
    c = context[0]
    staff = organisation["people"]["staff"]
    await sign_in(c, staff)
    body = content("248000")
    body["vendor"] = {
        **body["vendor"],
        "bank_name": "Private bank",
        "account_name": "Private beneficiary",
        "account_number": "0000000099",
    }
    req = (
        await c.post(
            "/api/v1/requisitions",
            json={
                "entity_id": organisation["entity_id"],
                "creation_key": str(uuid4()),
                "content": body,
            },
        )
    ).json()
    attachment = (await upload(c, req)).json()
    req = (await c.get("/api/v1/requisitions/" + req["id"])).json()
    req, _ = await signed(c, req, staff, "submit")
    await sign_in(c, administrator)
    path = "/api/v1/requisitions/" + req["id"]
    for suffix in ("", "?revision=1"):
        r = await c.get(path + suffix)
        assert r.status_code == 200 and "0000000099" not in r.text and "Private bank" not in r.text
        assert r.json()["content"]["vendor"]["account_number"] == "" and r.json()["oversight_only"]
        assert (
            r.json()["next_action"] is None
            or r.json()["next_action"]["actor_name"] == organisation["people"]["hod"]["name"]
        )
    for suffix in ("/attachments", "/attachments?revision=1"):
        r = await c.get(path + suffix)
        assert r.status_code == 200 and r.json()["access_restricted"] and r.json()["items"] == []
    for prefix, suffix in (
        ("/api/v1/attachments/", "/content"),
        ("/api/v1/access/attachments/", ""),
    ):
        assert (await c.get(prefix + attachment["id"] + suffix)).status_code == 404
    assert (
        await c.delete(
            "/api/v1/attachments/" + attachment["id"], params={"expected_version": req["version"]}
        )
    ).status_code == 404
    assert (await upload(c, req)).status_code == 403
    for action in ("approve", "reject", "return", "submit"):
        assert (
            await c.post(
                path + "/signing-challenges",
                json={
                    "expected_version": req["version"],
                    "action": action,
                    "reason": "Synthetic denial",
                },
            )
        ).status_code == 403
    assert (await c.get(path + "/history")).status_code == 200
    assert (await c.get("/api/v1/audit-events")).status_code == 403
    async with sessions() as s, s.begin():
        account = await s.get(Account, administrator["account_id"])
        account.permissions = sorted(SYSTEM_ADMIN_PERMISSIONS | {"vendor:read_sensitive"})
    assert (await c.get(path)).json()["content"]["vendor"]["account_number"] == "0000000099"
    assert (await c.get("/api/v1/attachments/" + attachment["id"] + "/content")).status_code == 404


async def test_admin_board_visibility_does_not_open_confidential_record(
    context, organisation, administrator
):
    from tests.board.test_board import act, setup

    c = context[0]
    case = await setup(c, organisation, "DEFER")
    case, _, _ = await act(c, case, organisation["people"]["secretary"], "board_submit")
    req = case["request"]
    await sign_in(c, administrator)
    path = "/api/v1/requisitions/" + req["id"]
    assert (await c.get(path)).status_code == 200
    assert (await c.get(path + "/board")).status_code == 404
    history = (await c.get(path + "/history")).json()
    assert all(not e.get("resolution_id") and not e.get("evidence_id") for e in history["items"])
    assert not any(e["type"] in ("board_recorded", "board_submitted") for e in history["items"])
    dash = (await c.get("/api/v1/dashboard")).json()
    assert not any(
        e["request_id"] == req["id"] and e["label"] == "Board resolution recorded"
        for e in dash["activity"]
    )


async def test_admin_vendor_reads_allow_all_companies_without_granting_writes(
    context, organisation, administrator, sessions
):
    c = context[0]
    await sign_in(c, organisation["people"]["staff"])
    made = (
        await c.post(
            "/api/v1/vendors", json={"entity_id": organisation["entity_id"], "data": vendor_data()}
        )
    ).json()
    await sign_in(c, administrator)
    companies = (await c.get("/api/v1/vendors/companies")).json()
    selected = next(e for e in companies if e["entity_id"] == organisation["entity_id"])
    assert not selected["can_create"]
    page = await c.get(
        "/api/v1/vendors",
        params={"entity_id": organisation["entity_id"], "search": "Synthetic", "limit": 1},
    )
    assert page.status_code == 200 and page.json()["total"] == 1 and "0000000001" not in page.text
    for suffix in ("", "/versions/1"):
        r = await c.get("/api/v1/vendors/" + made["id"] + suffix)
        assert (
            r.status_code == 200 and r.json()["data"]["bank"] is None and not r.json()["can_update"]
        )
    assert (
        await c.post(
            "/api/v1/vendors", json={"entity_id": organisation["entity_id"], "data": vendor_data()}
        )
    ).status_code == 403
    assert (
        await c.patch(
            "/api/v1/vendors/" + made["id"], json={"expected_version": 1, "data": vendor_data()}
        )
    ).status_code == 404
    async with sessions() as s, s.begin():
        (await s.get(Account, administrator["account_id"])).permissions = sorted(
            SYSTEM_ADMIN_PERMISSIONS | {"vendor:read_sensitive", "vendor:update"}
        )
    r = await c.get("/api/v1/vendors/" + made["id"])
    assert r.json()["data"]["bank"]["account_number"] == "0000000001" and not r.json()["can_update"]
    assert (
        await c.patch(
            "/api/v1/vendors/" + made["id"], json={"expected_version": 1, "data": vendor_data()}
        )
    ).status_code == 404
    async with sessions() as s, s.begin():
        (await s.get(Entity, UUID(organisation["entity_id"]))).active = False
    assert (await c.get("/api/v1/vendors/" + made["id"])).status_code == 200
    selected = next(
        e
        for e in (await c.get("/api/v1/vendors/companies")).json()
        if e["entity_id"] == organisation["entity_id"]
    )
    assert not selected["active"] and not selected["can_create"]


@pytest.mark.parametrize("loss", ["permission", "readonly", "disabled"])
async def test_oversight_revocation_is_immediate_for_existing_session(
    context, organisation, administrator, sessions, loss
):
    c = context[0]
    await sign_in(c, organisation["people"]["staff"])
    req = await draft(c, organisation, "1")
    await sign_in(c, administrator)
    assert (await c.get("/api/v1/requisitions/" + req["id"])).status_code == 200
    async with sessions() as s, s.begin():
        account = await s.get(Account, administrator["account_id"])
        if loss == "permission":
            account.permissions = ["staff:manage", "organisation:manage"]
        elif loss == "readonly":
            account.read_only = True
        else:
            account.active = False
    assert (await c.get("/api/v1/requisitions/" + req["id"])).status_code == (
        401 if loss == "disabled" else 404
    )
    assert (
        await c.get("/api/v1/vendors", params={"entity_id": organisation["entity_id"]})
    ).status_code == (401 if loss == "disabled" else 403)
    if loss != "disabled":
        assert (await c.get("/api/v1/vendors/companies")).json() == []
        assert (await c.get("/api/v1/dashboard")).json()["total"] == 0


async def test_admin_with_separate_requester_and_approver_roles_keeps_existing_rights(
    context, organisation, sessions
):
    c = context[0]
    p = organisation["people"]
    async with sessions() as s, s.begin():
        for role in ("staff", "hod"):
            account = await s.scalar(select(Account).where(Account.identity_id == p[role]["id"]))
            account.permissions = sorted(SYSTEM_ADMIN_PERMISSIONS)
    await sign_in(c, p["staff"])
    req = await draft(c, organisation, "1")
    assert not req["oversight_only"] and "edit" in req["available_actions"]
    req, _ = await signed(c, req, p["staff"], "submit")
    await sign_in(c, p["hod"])
    view = (await c.get("/api/v1/requisitions/" + req["id"])).json()
    assert not view["oversight_only"] and "approve" in view["available_actions"]
    req, _ = await signed(c, req, p["hod"], "approve")
    assert req["state"] == "APPROVED"
