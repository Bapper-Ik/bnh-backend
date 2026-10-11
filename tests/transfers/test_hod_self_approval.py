import asyncio
import io
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.core.errors import DomainError
from app.exports.models import Export
from app.identity.models import Account
from app.notifications.service import materialize_one
from app.organisation.models import Department, Membership, Office
from app.requisitions.models import Decision, Requisition, Revision, SigningChallenge
from app.transfers.models import DepartmentDebitAccount
from tests.exports.test_exports import generate
from tests.requisitions.test_approvals import command_for
from tests.requisitions.test_workflow import content, draft, sign_in, signed
from tests.transfers.test_transfers import DEBIT, configure

SUB_ACCOUNT = {
    **DEBIT,
    "account_name": "Synthetic department account",
    "account_number": "0076543210",
}


async def department_id(sessions, org):
    async with sessions() as s:
        member = await s.scalar(
            select(Membership).where(
                Membership.identity_id == org["people"]["hod"]["id"],
                Membership.entity_id == UUID(org["entity_id"]),
            )
        )
        return member.department_id


async def configure_department(sessions, org):
    dept = await department_id(sessions, org)
    async with sessions() as s, s.begin():
        s.add(DepartmentDebitAccount(department_id=dept, version=1, data=SUB_ACCOUNT))
    return dept


async def own_request(client, org, amount="248000.15"):
    person = org["people"]["hod"]
    await sign_in(client, person)
    req = await draft(client, org, amount)
    body = content(amount)
    body["vendor"].update(
        bank_name="Synthetic supplier bank",
        account_name="Synthetic supplier",
        account_number="0012345678",
    )
    saved = await client.put(
        f"/api/v1/requisitions/{req['id']}/draft",
        json={"expected_version": req["version"], "content": body},
    )
    assert saved.status_code == 200, saved.text
    return await signed(client, saved.json(), person, "submit")


@pytest.mark.parametrize("amount", ["1.00", "5000000.00"])
async def test_hod_explicit_self_approval_inbox_notification_and_frozen_department_letter(
    exports, organisation, sessions, amount
):
    client, app, _ = exports
    dept = await configure_department(sessions, organisation)
    await configure(sessions, organisation)
    req, submission = await own_request(client, organisation, amount)
    path = f"/api/v1/requisitions/{req['id']}"
    assert req["state"] == "PENDING_AUTHORITY"
    assert req["available_actions"] == ["approve", "retract"]
    inbox = (await client.get("/api/v1/requisitions?inbox=true")).json()
    assert req["id"] in [row["id"] for row in inbox["items"]]
    async with sessions() as s, s.begin():
        event = await s.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_id == UUID(req["id"]),
                AuditEvent.action == "requisition.submitted",
            )
        )
        assert await materialize_one(s, app.state.settings, event.id)
    alerts = (await client.get("/api/v1/notifications")).json()
    assert any(row["title"] == "Requisition needs your review" for row in alerts["items"])
    command = await command_for(client, req, organisation["people"]["hod"], "approve")
    bad = {**command, "challenge_id": submission["challenge_id"]}
    assert (await client.post(path + "/actions", json=bad)).status_code == 409
    responses = await asyncio.gather(
        *[client.post(path + "/actions", json=command) for _ in range(2)]
    )
    assert [r.status_code for r in responses] == [200, 200]
    async with sessions() as s, s.begin():
        rows = (
            await s.scalars(select(Export).where(Export.requisition_id == UUID(req["id"])))
        ).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.snapshot["transfer"]["debit_source"] == "department"
        assert row.snapshot["transfer"]["debit"]["account_number"] == "0076543210"
        revision = await s.get(Revision, row.revision_id)
        decision = await s.scalar(select(Decision).where(Decision.revision_id == row.revision_id))
        assert revision.policy_version == "bnh-doa-v2"
        assert revision.signature["challenge_id"] != decision.signature["challenge_id"]
        assert row.snapshot["signatures"][0]["strokes"] == decision.signature["strokes"]
        account = await s.get(DepartmentDebitAccount, dept)
        account.data = {**SUB_ACCOUNT, "account_number": "0099999999"}
        account.version += 1
        item = {"id": str(row.id)}
    await generate(exports, sessions, item)
    response = await client.get("/api/v1/exports/" + item["id"] + "/content")
    assert response.status_code == 200
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(response.content)).pages)
    assert "0076543210" in text and "0012345678" in text
    assert "0099999999" not in text and "0001234567" not in text
    assert "Synthetic hod" in text
    assert not (await client.get("/api/v1/requisitions?inbox=true")).json()["items"]
    await sign_in(client, organisation["people"]["other_hod"])
    assert (await client.get("/api/v1/exports/" + item["id"] + "/content")).status_code == 404


async def test_missing_department_account_never_uses_company_account(
    exports, organisation, sessions
):
    client, _, _ = exports
    await configure(sessions, organisation)
    req, _ = await own_request(client, organisation)
    result = await client.post(
        f"/api/v1/requisitions/{req['id']}/signing-challenges",
        json={"expected_version": req["version"], "action": "approve"},
    )
    transfer = result.json()["transfer_details"]
    assert transfer["debit_source"] == "department" and transfer["debit"] is None
    assert "Department sub-account and bank branch address" in transfer["missing"]
    req, _ = await signed(client, req, organisation["people"]["hod"], "approve")
    items = (await client.get(f"/api/v1/requisitions/{req['id']}/exports")).json()["items"]
    assert len(items) == 1 and items[0]["last_error"] == "transfer_details_missing"
    assert not items[0]["can_retry"]


@pytest.mark.parametrize("change", ["bank", "office", "department", "membership", "readonly"])
async def test_hod_signing_rechecks_department_and_current_eligibility(
    exports, organisation, sessions, change
):
    client, _, _ = exports
    dept = await configure_department(sessions, organisation)
    req, _ = await own_request(client, organisation)
    person = organisation["people"]["hod"]
    command = await command_for(client, req, person, "approve")
    async with sessions() as s, s.begin():
        if change == "bank":
            row = await s.get(DepartmentDebitAccount, dept)
            row.data = {**SUB_ACCOUNT, "account_number": "0099999999"}
            row.version += 1
        elif change == "office":
            row = await s.scalar(
                select(Office).where(Office.identity_id == person["id"], Office.role == "hod")
            )
            row.active = False
        elif change == "department":
            row = await s.get(Department, dept)
            row.active = False
        elif change == "membership":
            row = await s.scalar(select(Membership).where(Membership.identity_id == person["id"]))
            row.active = False
        else:
            row = await s.scalar(select(Account).where(Account.identity_id == person["id"]))
            row.read_only = True
    response = await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=command)
    assert response.status_code in {403, 409}, response.text
    async with sessions() as s:
        assert not await s.scalar(select(Export).where(Export.requisition_id == UUID(req["id"])))
        assert not await s.scalar(
            select(Decision).join(Revision).where(Revision.requisition_id == UUID(req["id"]))
        )
        challenge = await s.get(SigningChallenge, UUID(command["challenge_id"]))
        assert not challenge.consumed


async def test_department_account_admin_validation_conflicts_and_audit_rollback(
    exports, organisation, sessions, monkeypatch
):
    client, _, _ = exports
    dept = await department_id(sessions, organisation)
    path = f"/api/v1/organisation/departments/{dept}/debit-account"
    await sign_in(client, organisation["people"]["hod"])
    assert (await client.get(path)).status_code == 403
    assert (
        await client.put(path, json={"expected_version": 0, "data": SUB_ACCOUNT})
    ).status_code == 403
    person = organisation["people"]["staff"]
    async with sessions() as s, s.begin():
        account = await s.scalar(select(Account).where(Account.identity_id == person["id"]))
        account.permissions = ["organisation:manage"]
    await sign_in(client, person)
    assert (await client.get(path)).json() == {"version": 0, "data": None}
    for number in ["123", "12345678901", "１２３４５６７８９０"]:
        assert (
            await client.put(
                path,
                json={"expected_version": 0, "data": {**SUB_ACCOUNT, "account_number": number}},
            )
        ).status_code == 422
    response = await client.put(path, json={"expected_version": 0, "data": SUB_ACCOUNT})
    assert response.status_code == 200 and response.json()["data"]["account_number"] == "0076543210"
    assert (
        await client.put(path, json={"expected_version": 0, "data": SUB_ACCOUNT})
    ).status_code == 409

    async def failed(*args, **kwargs):
        raise DomainError("SERVICE_UNAVAILABLE", "Synthetic audit outage", 503)

    with monkeypatch.context() as patch:
        patch.setattr("app.transfers.router.record_event", failed)
        assert (
            await client.put(
                path, json={"expected_version": 1, "data": {**SUB_ACCOUNT, "bank_name": "Changed"}}
            )
        ).status_code == 503
    assert (await client.get(path)).json() == {"version": 1, "data": SUB_ACCOUNT}
    async with sessions() as s, s.begin():
        row = await s.get(Department, dept)
        row.active = False
    assert (
        await client.put(path, json={"expected_version": 1, "data": SUB_ACCOUNT})
    ).status_code == 403
    assert (
        await client.get(f"/api/v1/organisation/departments/{uuid4()}/debit-account")
    ).status_code == 404


async def test_existing_v1_hod_request_keeps_chief_of_staff_and_company_debit(
    exports, organisation, sessions, monkeypatch
):
    from app.authority.policy import Authority, resolve

    client, _, _ = exports
    await configure(sessions, organisation)
    await configure_department(sessions, organisation)

    def old_policy(total, offices):
        route = resolve(total, offices)
        return replace(
            route,
            authority=Authority.CHIEF_OF_STAFF,
            requester_floor=Authority.CHIEF_OF_STAFF,
            policy_version="bnh-doa-v1",
        )

    with monkeypatch.context() as patch:
        patch.setattr("app.requisitions.service.resolve", old_policy)
        req, _ = await own_request(client, organisation)
    assert req["required_authority"] == "chief_of_staff"
    assert "approve" not in req["available_actions"]
    path = f"/api/v1/requisitions/{req['id']}"
    assert (
        await client.post(
            path + "/signing-challenges",
            json={"expected_version": req["version"], "action": "approve"},
        )
    ).status_code == 409
    assert not (await client.get("/api/v1/requisitions?inbox=true")).json()["items"]
    await sign_in(client, organisation["people"]["chief_of_staff"])
    req, _ = await signed(client, req, organisation["people"]["chief_of_staff"], "approve")
    async with sessions() as s:
        export = await s.scalar(select(Export).where(Export.requisition_id == UUID(req["id"])))
        assert export.snapshot["policy"] == "bnh-doa-v1"
        assert export.snapshot["transfer"]["debit_source"] == "company"
        assert export.snapshot["transfer"]["debit"]["account_number"] == "0001234567"


async def test_self_approval_audit_failure_rolls_back_signature_decision_and_letter(
    exports, organisation, sessions, monkeypatch
):
    client, _, _ = exports
    await configure_department(sessions, organisation)
    req, _ = await own_request(client, organisation)
    person = organisation["people"]["hod"]
    command = await command_for(client, req, person, "approve")

    async def fail(*args, **kwargs):
        raise DomainError("SERVICE_UNAVAILABLE", "Synthetic audit failure", 503)

    with monkeypatch.context() as patch:
        patch.setattr("app.transfers.service.record_event", fail)
        assert (
            await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=command)
        ).status_code == 503
    async with sessions() as s:
        request = await s.get(Requisition, UUID(req["id"]))
        assert request.state == "PENDING_AUTHORITY"
        assert not await s.scalar(
            select(Decision).where(Decision.revision_id == request.current_revision_id)
        )
        assert not await s.scalar(select(Export).where(Export.requisition_id == request.id))
        assert not (await s.get(SigningChallenge, UUID(command["challenge_id"]))).consumed
    assert (
        await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=command)
    ).status_code == 200
