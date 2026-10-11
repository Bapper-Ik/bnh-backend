import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.audit.models import AuditEvent
from app.exports.models import Export
from app.identity.models import Account
from app.requisitions.models import Decision, Requisition, Revision
from tests.requisitions.test_creation import context as context
from tests.requisitions.test_creation import organisation as organisation
from tests.requisitions.test_creation import upload
from tests.requisitions.test_workflow import content, draft, sign_in, signed


def command(req):
    return {"expected_version": req["version"], "idempotency_key": str(uuid4())}


async def test_delete_draft_is_private_idempotent_and_revokes_documents(
    context, organisation, sessions
):
    client, _, _ = context
    people = organisation["people"]
    await sign_in(client, people["staff"])
    create = {
        "entity_id": organisation["entity_id"],
        "creation_key": str(uuid4()),
        "content": content("10"),
    }
    req = (await client.post("/api/v1/requisitions", json=create)).json()
    path = "/api/v1/requisitions/" + req["id"]
    file = (await upload(client, req)).json()
    req = (await client.get(path)).json()
    export = await client.post(path + "/exports", json={**command(req), "include_board": False})
    assert export.status_code == 202, export.text
    body = command(req)
    await sign_in(client, people["hod"])
    assert (await client.post(path + "/delete", json=body)).status_code == 404
    await sign_in(client, people["staff"])
    assert (
        await client.post(path + "/delete", json={**body, "expected_version": req["version"] - 1})
    ).status_code == 409
    assert (await client.post(path + "/delete", json=body)).status_code == 200
    assert (await client.post(path + "/delete", json=body)).status_code == 200
    assert (await client.get(path)).status_code == 404
    assert (await client.get("/api/v1/attachments/" + file["id"] + "/content")).status_code == 404
    assert (await client.get("/api/v1/exports/" + export.json()["id"])).status_code == 404
    assert (await client.get("/api/v1/requisitions", params={"search": req["reference"]})).json()[
        "total"
    ] == 0
    assert (await client.post("/api/v1/requisitions", json=create)).status_code == 404
    async with sessions() as s:
        stored = await s.get(Requisition, UUID(req["id"]))
        assert stored.deleted_at is not None and stored.state == "DRAFT"
        count = await s.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.resource_id == stored.id, AuditEvent.action == "requisition.deleted")
        )
        assert count == 1


async def test_retraction_preserves_signed_revision_and_resubmits_with_fresh_route(
    context, organisation, sessions
):
    client, app, _ = context
    people = organisation["people"]
    await sign_in(client, people["staff"])
    req, _ = await signed(
        client, await draft(client, organisation, "10"), people["staff"], "submit"
    )
    path = "/api/v1/requisitions/" + req["id"]
    async with sessions() as s:
        rev = await s.scalar(select(Revision).where(Revision.requisition_id == UUID(req["id"])))
        original = rev.content, rev.signature
    assert (await client.post(path + "/delete", json=command(req))).status_code == 403
    result = await client.post(path + "/retract", json=(body := command(req)))
    assert result.status_code == 200, result.text
    req = (await client.get(path)).json()
    assert req["state"] == "DRAFT" and "delete" in req["available_actions"]
    assert any(e["type"] == "requisition.retracted" for e in req["history"])
    assert (await client.post(path + "/retract", json=body)).status_code == 200
    await sign_in(client, people["hod"])
    assert (await client.get(path)).status_code == 404
    assert (await client.get("/api/v1/approvals/inbox")).json()["total"] == 0
    await sign_in(client, people["staff"])
    edited = await client.put(
        path + "/draft", json={"expected_version": req["version"], "content": content("24000000")}
    )
    assert edited.status_code == 200
    req, _ = await signed(client, edited.json(), people["staff"], "submit")
    assert req["revision_number"] == 2 and req["required_authority"] == "chief_of_staff"
    async with sessions() as s:
        revisions = (
            await s.scalars(
                select(Revision)
                .where(Revision.requisition_id == UUID(req["id"]))
                .order_by(Revision.number)
            )
        ).all()
        assert len(revisions) == 2
        assert (revisions[0].content, revisions[0].signature) == original
        assert revisions[1].signature["challenge_id"] != revisions[0].signature["challenge_id"]


@pytest.mark.parametrize("decision", ["approve", "reject", "return"])
async def test_requester_cannot_retract_after_approver_action(context, organisation, decision):
    client, _, _ = context
    people = organisation["people"]
    await sign_in(client, people["staff"])
    req, _ = await signed(
        client, await draft(client, organisation, "10"), people["staff"], "submit"
    )
    await sign_in(client, people["hod"])
    req, _ = await signed(client, req, people["hod"], decision, "Synthetic decision")
    await sign_in(client, people["staff"])
    result = await client.post(f"/api/v1/requisitions/{req['id']}/retract", json=command(req))
    assert result.status_code == 403


@pytest.mark.parametrize("started", [False, True])
async def test_board_retraction_stops_when_resolution_work_starts(context, organisation, started):
    from tests.board.test_board import data, save

    client, _, _ = context
    people = organisation["people"]
    await sign_in(client, people["staff"])
    req, _ = await signed(
        client, await draft(client, organisation, "600000000"), people["staff"], "submit"
    )
    path = "/api/v1/requisitions/" + req["id"]
    if started:
        await sign_in(client, people["secretary"])
        await save(client, req, data())
    await sign_in(client, people["staff"])
    req = (await client.get(path)).json()
    assert ("retract" in req["available_actions"]) is not started
    result = await client.post(path + "/retract", json=command(req))
    assert result.status_code == (403 if started else 200), result.text


@pytest.mark.parametrize("action", ["delete", "retract"])
async def test_management_readonly_denial_and_audit_rollback(
    context, organisation, sessions, monkeypatch, action
):
    client, _, _ = context
    person = organisation["people"]["staff"]
    await sign_in(client, person)
    req = await draft(client, organisation, "10")
    if action == "retract":
        req, _ = await signed(client, req, person, "submit")
    path = f"/api/v1/requisitions/{req['id']}"
    async with sessions() as s, s.begin():
        account = await s.scalar(select(Account).where(Account.identity_id == person["id"]))
        account.read_only = True
    assert (await client.post(path + "/" + action, json=command(req))).status_code == 403
    async with sessions() as s, s.begin():
        account = await s.scalar(select(Account).where(Account.identity_id == person["id"]))
        account.read_only = False

    async def fail(*args, **kwargs):
        raise SQLAlchemyError("Synthetic audit failure")

    monkeypatch.setattr("app.requisitions.router.record_event", fail)
    assert (await client.post(path + "/" + action, json=command(req))).status_code == 503
    restored = (await client.get(path)).json()
    assert restored["state"] == req["state"] and restored["version"] == req["version"]


async def test_retraction_racing_approval_has_one_winner(context, organisation, sessions):
    client, app, _ = context
    people = organisation["people"]
    await sign_in(client, people["staff"])
    req, _ = await signed(
        client, await draft(client, organisation, "10"), people["staff"], "submit"
    )
    path = "/api/v1/requisitions/" + req["id"]
    async with AsyncClient(
        transport=ASGITransport(app),
        base_url="http://test",
        headers={"origin": "http://localhost:5173"},
    ) as approver:
        await sign_in(approver, people["hod"])
        intent = {"expected_version": req["version"], "action": "approve", "reason": ""}
        challenge = (await approver.post(path + "/signing-challenges", json=intent)).json()
        approval = {
            **intent,
            "challenge_id": challenge["id"],
            "idempotency_key": str(uuid4()),
            "signer_name": people["hod"]["name"],
            "consent": True,
            "strokes": [[{"x": 0.1, "y": 0.2}, {"x": 0.2, "y": 0.3}, {"x": 0.4, "y": 0.5}]],
        }
        results = await asyncio.gather(
            client.post(path + "/retract", json=command(req)),
            approver.post(path + "/actions", json=approval),
        )
        assert sorted(r.status_code for r in results)[0] == 200
        assert sum(r.status_code == 200 for r in results) == 1
        assert all(r.status_code in [200, 403, 404, 409] for r in results), [
            (r.status_code, r.text) for r in results
        ]
    async with sessions() as s:
        row = await s.get(Requisition, UUID(req["id"]))
        decision = await s.scalar(
            select(Decision).where(Decision.revision_id == row.current_revision_id)
        )
        export = await s.scalar(select(Export).where(Export.requisition_id == row.id))
        assert (decision is not None) == (row.state == "APPROVED")
        assert (export is not None) == (row.state == "APPROVED")
