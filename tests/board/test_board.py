import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.audit.models import AuditEvent, OutboxItem
from app.board.models import ChairmanDecision, Resolution
from app.core.errors import DomainError
from app.organisation.models import Office
from app.requisitions.models import Requisition, SigningChallenge
from tests.requisitions.test_creation import context as context
from tests.requisitions.test_creation import png
from tests.requisitions.test_workflow import draft, sign_in, signed
from tests.requisitions.test_workflow import organisation as organisation


def data(amount="600000000.00", outcome="APPROVE", **extra):
    return dict(
        meeting_date="2026-01-01",
        board_name="Synthetic Board",
        reference="SYN-001",
        decision_text="Actual synthetic meeting decision",
        outcome=outcome,
        authorised_amount=amount,
        conditions="Obtain permit first" if outcome == "CONDITIONAL_APPROVE" else "",
        attendance="Synthetic attendees",
        quorum_attested=True,
        quorum_basis="Synthetic charter reference",
        **extra,
    )


async def setup(client, org, outcome="APPROVE", requester="staff"):
    person = org["people"][requester]
    amount = "600000000.00" if requester != "md" else "1.00"
    await sign_in(client, person)
    req, _ = await signed(client, await draft(client, org, amount), person, "submit")
    await sign_in(client, org["people"]["secretary"])
    case = await save(client, req, data(amount, outcome))
    return await upload(client, case)


async def save(client, req, fields):
    result = await client.post(
        f"/api/v1/requisitions/{req['id']}/board-resolutions",
        json={"expected_version": req["version"], "idempotency_key": str(uuid4()), "data": fields},
    )
    assert result.status_code == 200, result.text
    return result.json()


async def upload(client, case):
    result = await client.post(
        f"/api/v1/board-resolutions/{case['records'][-1]['id']}/attachments",
        params={
            "expected_version": case["request"]["version"],
            "upload_key": str(uuid4()),
            "filename": "formal-resolution.png",
        },
        content=png(),
        headers={"content-type": "image/png"},
    )
    assert result.status_code == 200, result.text
    return result.json()


async def prepare(client, case, person, action, reason=""):
    intent = {"action": action, "expected_version": case["request"]["version"], "reason": reason}
    path = f"/api/v1/board-resolutions/{case['records'][-1]['id']}"
    r = await client.post(path + "/signing-challenges", json=intent)
    assert r.status_code == 201, r.text
    return path, {
        **intent,
        "challenge_id": r.json()["id"],
        "idempotency_key": str(uuid4()),
        "signer_name": person["name"],
        "consent": True,
        "strokes": [[{"x": 0, "y": 0}, {"x": 0.2, "y": 0.5}, {"x": 0.4, "y": 0.2}]],
    }


async def act(client, case, person, action, reason=""):
    path, command = await prepare(client, case, person, action, reason)
    result = await client.post(path + "/actions", json=command)
    assert result.status_code == 200, result.text
    loaded = await client.get(f"/api/v1/requisitions/{case['request']['id']}/board")
    assert loaded.status_code == 200, loaded.text
    return loaded.json(), path, command


@pytest.mark.parametrize(
    "outcome,state",
    [
        ("APPROVE", "APPROVED"),
        ("REJECT", "REJECTED"),
        ("DEFER", "DEFERRED"),
        ("CONDITIONAL_APPROVE", "CONDITIONALLY_APPROVED"),
    ],
)
async def test_outcomes_private_evidence_and_two_signers(
    context, organisation, sessions, outcome, state
):
    client, _, _ = context
    people = organisation["people"]
    case = await setup(client, organisation, outcome)
    req = case["request"]
    record = case["records"][-1]
    assert req["state"] == "AWAITING_BOARD_RESOLUTION"
    assert record["data"]["meeting_date"] != record["recorded_at"][:10]
    assert (await client.get("/api/v1/approvals/inbox")).json()["total"] == 1
    case, _, _ = await act(client, case, people["secretary"], "board_submit")
    assert case["request"]["state"] == "AWAITING_CHAIRMAN_SIGNOFF"
    assert (await client.get("/api/v1/approvals/inbox")).json()["total"] == 0
    file_id = record["evidence"]["id"]
    for role in ["staff", "md", "hod", "other_hod"]:
        await sign_in(client, people[role])
        assert (await client.get(f"/api/v1/requisitions/{req['id']}/board")).status_code == 404
        assert (await client.get(f"/api/v1/attachments/{file_id}/content")).status_code == 404
    await sign_in(client, people["chairman"])
    assert (await client.get("/api/v1/auth/me")).json()["can_access_approval_inbox"] is True
    assert (await client.get("/api/v1/approvals/inbox")).json()["total"] == 1
    assert (await client.get(f"/api/v1/attachments/{file_id}/content")).content == png()
    case, path, command = await act(client, case, people["chairman"], "board_confirm")
    assert case["request"]["state"] == state
    assert case["records"][0]["secretary_name"] != case["records"][0]["chairman_name"]
    replay = await client.post(path + "/actions", json=command)
    assert replay.status_code == 200 and replay.json()["state"] == state
    assert (await client.get("/api/v1/approvals/inbox")).json()["total"] == 0
    command["reason"] = "changed"
    assert (await client.post(path + "/actions", json=command)).status_code == 409
    async with sessions() as s:
        assert (
            await s.scalar(
                select(func.count())
                .select_from(ChairmanDecision)
                .where(ChairmanDecision.resolution_id == UUID(record["id"]))
            )
            == 1
        )
        events = (
            await s.scalars(
                select(AuditEvent).where(
                    AuditEvent.resource_id == UUID(req["id"]),
                    AuditEvent.action.in_(["board.recorded", "board.confirmed"]),
                )
            )
        ).all()
        assert len(events) == 2
        for event in events:
            assert await s.scalar(
                select(OutboxItem.id).where(
                    OutboxItem.event_id == event.id,
                    OutboxItem.destination == "requisition_notification",
                )
            )
    for table in ["board_resolutions", "board_chairman_decisions"]:
        with pytest.raises(DBAPIError):
            async with sessions() as s, s.begin():
                await s.execute(text(f"UPDATE custodian.{table} SET id=id"))
    await sign_in(client, people["staff"])
    visible = (await client.get(f"/api/v1/requisitions/{req['id']}")).json()
    assert visible["state"] == state and "Actual synthetic" not in str(visible["history"])
    assert (await client.get(f"/api/v1/requisitions/{req['id']}?revision=1")).json()[
        "state"
    ] == state


async def test_correction_and_later_resolution_keep_hold_and_old_records(context, organisation):
    client, _, _ = context
    p = organisation["people"]
    case = await setup(client, organisation, "CONDITIONAL_APPROVE", requester="md")
    original = case["request"]["content"]
    case, _, _ = await act(client, case, p["secretary"], "board_submit")
    await sign_in(client, p["chairman"])
    oldpath, stale = await prepare(client, case, p["chairman"], "board_confirm")
    case, _, _ = await act(
        client, case, p["chairman"], "board_return", "Correct the resolution reference."
    )
    assert case["records"][-1]["return_reason"]
    await sign_in(client, p["md"])
    assert (
        await client.post(
            f"/api/v1/requisitions/{case['request']['id']}/revisions",
            json={"expected_version": case["request"]["version"], "idempotency_key": str(uuid4())},
        )
    ).status_code == 403
    await sign_in(client, p["secretary"])
    fields = {
        **case["records"][-1]["data"],
        "reference": "SYN-002",
        "correction_summary": "Corrected reference",
    }
    case = await save(client, case["request"], fields)
    assert len(case["records"]) == 2 and case["records"][-1]["submitted_at"] is None
    assert case["records"][-1]["evidence"]["id"] == case["records"][0]["evidence"]["id"]
    case, _, _ = await act(client, case, p["secretary"], "board_submit")
    await sign_in(client, p["chairman"])
    assert (await client.post(oldpath + "/actions", json=stale)).status_code == 403
    case, _, _ = await act(client, case, p["chairman"], "board_confirm")
    assert case["request"]["state"] == "CONDITIONALLY_APPROVED"
    await sign_in(client, p["secretary"])
    fields = {
        **fields,
        "reference": "SYN-003",
        "outcome": "APPROVE",
        "meeting_date": "2026-01-02",
        "conditions": "Conditions satisfied at later meeting",
    }
    case = await save(client, case["request"], fields)
    assert case["records"][-1]["kind"] == "later_resolution" and not case["records"][-1]["evidence"]
    assert case["request"]["state"] == "CONDITIONALLY_APPROVED"
    case = await upload(client, case)
    case, _, _ = await act(client, case, p["secretary"], "board_submit")
    assert case["request"]["state"] == "CONDITIONALLY_APPROVED"
    await sign_in(client, p["chairman"])
    assert (await client.get("/api/v1/approvals/inbox")).json()["total"] == 1
    case, _, _ = await act(client, case, p["chairman"], "board_confirm")
    assert case["request"]["state"] == "APPROVED"
    assert case["request"]["content"] == original
    assert [r["status"] for r in case["records"]] == [
        "RETURNED_TO_SECRETARY",
        "CONDITIONALLY_APPROVED",
        "APPROVED",
    ]


@pytest.mark.parametrize(
    "bad",
    [
        {"meeting_date": "2999-01-01"},
        {"authorised_amount": "1"},
        {"quorum_attested": False},
        {"attendance": " "},
        {"outcome": "CONDITIONAL_APPROVE", "conditions": ""},
    ],
)
async def test_invalid_meeting_data_blocks_signature(context, organisation, bad):
    client, _, _ = context
    case = await setup(client, organisation)
    case = await save(client, case["request"], {**case["records"][-1]["data"], **bad})
    result = await client.post(
        f"/api/v1/board-resolutions/{case['records'][-1]['id']}/signing-challenges",
        json={"action": "board_submit", "expected_version": case["request"]["version"]},
    )
    assert result.status_code == 422, result.text


async def test_missing_evidence_wrong_role_and_ordinary_endpoint(context, organisation):
    client, _, _ = context
    p = organisation["people"]
    await sign_in(client, p["staff"])
    req, _ = await signed(
        client, await draft(client, organisation, "600000000"), p["staff"], "submit"
    )
    await sign_in(client, p["secretary"])
    case = await save(client, req, data())
    path = f"/api/v1/board-resolutions/{case['records'][-1]['id']}"
    assert (
        await client.post(
            path + "/signing-challenges",
            json={"action": "board_submit", "expected_version": case["request"]["version"]},
        )
    ).status_code == 422
    await sign_in(client, p["chairman"])
    assert (
        await client.post(
            path + "/signing-challenges",
            json={"action": "board_confirm", "expected_version": case["request"]["version"]},
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/requisitions/{req['id']}/signing-challenges",
            json={"action": "approve", "expected_version": case["request"]["version"]},
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/requisitions/{req['id']}/board-resolutions",
            json={
                "expected_version": case["request"]["version"],
                "idempotency_key": str(uuid4()),
                "data": data(),
            },
        )
    ).status_code == 403


async def test_revoked_office_stale_evidence_expiry_storage_and_audit_failure(
    context, organisation, sessions, monkeypatch
):
    client, _, storage = context
    p = organisation["people"]
    case = await setup(client, organisation)
    path, command = await prepare(client, case, p["secretary"], "board_submit")
    case = await upload(client, case)
    assert (await client.post(path + "/actions", json=command)).status_code == 409
    path, command = await prepare(client, case, p["secretary"], "board_submit")
    async with sessions() as s, s.begin():
        challenge = await s.get(SigningChallenge, UUID(command["challenge_id"]))
        challenge.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert (await client.post(path + "/actions", json=command)).status_code == 409
    path, command = await prepare(client, case, p["secretary"], "board_submit")
    files = storage.files.copy()
    storage.files.clear()
    assert (await client.post(path + "/actions", json=command)).status_code == 503
    storage.files.update(files)
    original = __import__("app.board.router", fromlist=["record_event"]).record_event

    async def fail(s, **kwargs):
        if kwargs["action"] == "board.recorded":
            raise DomainError("SERVICE_UNAVAILABLE", "Synthetic audit unavailable.", 503)
        return await original(s, **kwargs)

    monkeypatch.setattr("app.board.router.record_event", fail)
    assert (await client.post(path + "/actions", json=command)).status_code == 503
    async with sessions() as s:
        assert not (await s.get(SigningChallenge, UUID(command["challenge_id"]))).consumed
        assert not (await s.get(Resolution, UUID(case["records"][-1]["id"]))).signature
    monkeypatch.setattr("app.board.router.record_event", original)
    async with sessions() as s, s.begin():
        office = await s.scalar(select(Office).where(Office.identity_id == p["secretary"]["id"]))
        office.active = False
    assert (await client.post(path + "/actions", json=command)).status_code in [404, 409]


async def test_concurrent_confirm_return_single_outcome_and_material_mismatch(
    context, organisation, sessions
):
    client, _, _ = context
    p = organisation["people"]
    case = await setup(client, organisation)
    case, _, _ = await act(client, case, p["secretary"], "board_submit")
    await sign_in(client, p["chairman"])
    path, confirm = await prepare(client, case, p["chairman"], "board_confirm")
    _, returned = await prepare(client, case, p["chairman"], "board_return", "Correction required")
    async with sessions() as s, s.begin():
        req = await s.get(Requisition, UUID(case["request"]["id"]))
        req.total = 1
    assert (await client.post(path + "/actions", json=confirm)).status_code == 409
    async with sessions() as s, s.begin():
        req = await s.get(Requisition, UUID(case["request"]["id"]))
        req.total = 600000000
    results = await asyncio.gather(
        *[client.post(path + "/actions", json=body) for body in (confirm, returned)]
    )
    assert sorted(r.status_code for r in results) == [200, 403]
    async with sessions() as s:
        assert (
            await s.scalar(
                select(func.count())
                .select_from(ChairmanDecision)
                .where(ChairmanDecision.resolution_id == UUID(case["records"][-1]["id"]))
            )
            == 1
        )


async def test_requester_secretary_can_record_but_cannot_confirm(context, organisation):
    client, _, _ = context
    p = organisation["people"]
    case = await setup(client, organisation, requester="secretary")
    assert (await client.get("/api/v1/approvals/inbox")).json()["total"] == 1
    case, path, _ = await act(client, case, p["secretary"], "board_submit")
    assert (
        await client.post(
            path + "/signing-challenges",
            json={"action": "board_confirm", "expected_version": case["request"]["version"]},
        )
    ).status_code == 403


@pytest.mark.parametrize("conflict", ["same_person", "chairman_requester", "missing_chairman"])
async def test_conflicted_board_appointments_block_submission(
    context, organisation, sessions, conflict
):
    client, _, _ = context
    p = organisation["people"]
    await sign_in(client, p["staff"])
    req = await draft(client, organisation, "600000000")
    async with sessions() as s, s.begin():
        office = await s.scalar(select(Office).where(Office.identity_id == p["chairman"]["id"]))
        if conflict == "same_person":
            office.identity_id = p["secretary"]["id"]
        elif conflict == "chairman_requester":
            office.identity_id = p["staff"]["id"]
        else:
            office.active = False
    result = await client.post(
        f"/api/v1/requisitions/{req['id']}/signing-challenges",
        json={"expected_version": req["version"], "action": "submit"},
    )
    assert result.status_code == 409
    assert result.json()["code"] in {
        "SELF_APPROVAL_PROHIBITED",
        "BOARD_SEPARATION_REQUIRED",
        "AUTHORITY_ASSIGNMENT_BLOCKED",
    }


async def test_board_draft_idempotency_stale_updates_and_private_review_grant(
    context, organisation, sessions
):
    from app.access.models import ReviewGrant
    from app.identity.models import Account

    client, _, _ = context
    p = organisation["people"]
    case = await setup(client, organisation)
    req = case["request"]
    body = {
        "expected_version": req["version"],
        "idempotency_key": str(uuid4()),
        "data": {**case["records"][-1]["data"], "reference": "SYN-002"},
    }
    path = f"/api/v1/requisitions/{req['id']}/board-resolutions"
    first = await client.post(path, json=body)
    assert first.status_code == 200
    assert (await client.post(path, json=body)).json() == first.json()
    body["data"]["reference"] = "Different intent"
    assert (await client.post(path, json=body)).status_code == 409
    body["idempotency_key"] = str(uuid4())
    assert (await client.post(path, json=body)).status_code == 409
    file_id = case["records"][-1]["evidence"]["id"]
    async with sessions() as s, s.begin():
        account = await s.scalar(select(Account).where(Account.identity_id == p["staff"]["id"]))
        account.permissions = ["staff:manage", "organisation:manage", "office_assignment:manage"]
    await sign_in(client, p["staff"])
    assert (await client.get(f"/api/v1/attachments/{file_id}/content")).status_code == 404
    assert (await client.post(path, json=body)).status_code == 404
    async with sessions() as s, s.begin():
        account = await s.scalar(select(Account).where(Account.identity_id == p["staff"]["id"]))
        account.read_only = True
        s.add(
            ReviewGrant(identity_id=account.identity_id, entity_id=UUID(organisation["entity_id"]))
        )
    assert (await client.get(f"/api/v1/requisitions/{req['id']}")).status_code == 200
    assert (await client.get(f"/api/v1/requisitions/{req['id']}/board")).status_code == 404
    assert (await client.get(f"/api/v1/attachments/{file_id}/content")).status_code == 404
