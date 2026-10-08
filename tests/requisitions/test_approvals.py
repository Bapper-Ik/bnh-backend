"""Release approval journey: real PostgreSQL, current authority and preserved revisions."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.audit.models import AuditEvent, OutboxItem
from app.identity.models import Account
from app.organisation.models import Office
from app.requisitions.models import Decision, Requisition, Revision, SigningChallenge
from tests.requisitions.test_creation import context as context
from tests.requisitions.test_creation import png, upload
from tests.requisitions.test_workflow import (
    content,
    draft,
    sign_in,
    signed,
)
from tests.requisitions.test_workflow import (
    organisation as organisation,
)


async def command_for(client, req, person, action, reason=""):
    intent = {"expected_version": req["version"], "action": action, "reason": reason}
    response = await client.post(
        f"/api/v1/requisitions/{req['id']}/signing-challenges", json=intent
    )
    assert response.status_code == 201, response.text
    return {
        **intent,
        "challenge_id": response.json()["id"],
        "idempotency_key": str(uuid4()),
        "signer_name": person["name"],
        "consent": True,
        "strokes": [[{"x": 0.1, "y": 0.2}, {"x": 0.2, "y": 0.4}, {"x": 0.5, "y": 0.2}]],
    }


async def pending(client, org, amount="4000000"):
    person = org["people"]["staff"]
    await sign_in(client, person)
    req, _ = await signed(client, await draft(client, org, amount), person, "submit")
    return req


@pytest.mark.parametrize(
    "amount,role", [("5000000", "hod"), ("5000000.01", "chief_of_staff"), ("100000000.01", "md")]
)
async def test_release_inbox_and_decisions(context, organisation, amount, role):
    client, _, _ = context
    req = await pending(client, organisation, amount)
    people = organisation["people"]
    for denied in {"staff", "other_hod", "secretary", "chairman", "hod", "chief_of_staff", "md"} - {
        role
    }:
        await sign_in(client, people[denied])
        page = (
            await client.get("/api/v1/approvals/inbox", params={"search": req["reference"]})
        ).json()
        assert page["total"] == 0
        response = await client.post(
            f"/api/v1/requisitions/{req['id']}/signing-challenges",
            json={"expected_version": req["version"], "action": "approve"},
        )
        assert response.status_code in {403, 404, 409}
    await sign_in(client, people[role])
    page = (
        await client.get("/api/v1/approvals/inbox", params={"search": req["reference"], "limit": 1})
    ).json()
    assert page["total"] == 1 and page["items"][0]["id"] == req["id"]
    assert (
        await client.get(
            "/api/v1/approvals/inbox", params={"search": req["reference"], "offset": 1}
        )
    ).json()["items"] == []
    detail = (await client.get(f"/api/v1/requisitions/{req['id']}")).json()
    assert detail["available_actions"] == ["approve", "reject", "return"]
    result, command = await signed(client, req, people[role], "approve")
    assert result["state"] == "APPROVED" and result["available_actions"] == []
    assert (
        await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=command)
    ).json() == result
    assert (
        await client.get("/api/v1/approvals/inbox", params={"search": req["reference"]})
    ).json()["total"] == 0
    await sign_in(client, people["staff"])
    assert (
        await client.put(
            f"/api/v1/requisitions/{req['id']}/draft",
            json={"expected_version": result["version"], "content": content("1")},
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/requisitions/{req['id']}/revisions",
            json={"expected_version": result["version"], "idempotency_key": str(uuid4())},
        )
    ).status_code == 403


@pytest.mark.parametrize("action", ["reject", "return"])
async def test_reason_required_and_bound_to_signature(context, organisation, action):
    client, _, _ = context
    req = await pending(client, organisation)
    person = organisation["people"]["hod"]
    await sign_in(client, person)
    invalid = await client.post(
        f"/api/v1/requisitions/{req['id']}/signing-challenges",
        json={"expected_version": req["version"], "action": action, "reason": "  "},
    )
    assert invalid.status_code == 422
    cmd = await command_for(client, req, person, action, "Please explain the cost.")
    forged = await client.post(
        f"/api/v1/requisitions/{req['id']}/actions", json={**cmd, "reason": "Different reason"}
    )
    assert forged.status_code == 409 and forged.json()["code"] == "SIGNATURE_INVALID"
    response = await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=cmd)
    assert response.status_code == 200
    assert response.json()["history"][-1]["reason"] == cmd["reason"]


@pytest.mark.parametrize("change", ["revoked", "expired", "readonly", "disabled"])
async def test_privileges_rechecked_between_challenge_and_decision(
    context, organisation, sessions, change
):
    client, _, _ = context
    req = await pending(client, organisation)
    person = organisation["people"]["hod"]
    await sign_in(client, person)
    cmd = await command_for(client, req, person, "approve")
    async with sessions() as s, s.begin():
        if change in {"revoked", "expired"}:
            await s.execute(
                update(Office)
                .where(Office.identity_id == person["id"])
                .values(
                    **(
                        {"active": False}
                        if change == "revoked"
                        else {"valid_until": datetime.now(UTC) - timedelta(seconds=1)}
                    )
                )
            )
        else:
            await s.execute(
                update(Account)
                .where(Account.identity_id == person["id"])
                .values(**({"active": False} if change == "disabled" else {"read_only": True}))
            )
    response = await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=cmd)
    assert response.status_code in {401, 403, 404}
    async with sessions() as s:
        assert (
            await s.scalar(
                select(func.count())
                .select_from(Decision)
                .where(
                    Decision.revision_id
                    == select(Revision.id)
                    .where(Revision.requisition_id == UUID(req["id"]))
                    .scalar_subquery()
                )
            )
            == 0
        )


async def test_competing_decisions_single_winner_and_retry(context, organisation, sessions):
    client, app, _ = context
    req = await pending(client, organisation)
    person = organisation["people"]["hod"]
    await sign_in(client, person)
    approve = await command_for(client, req, person, "approve")
    reject = await command_for(client, req, person, "reject", "Not needed")
    responses = await asyncio.gather(
        *[
            client.post(f"/api/v1/requisitions/{req['id']}/actions", json=cmd)
            for cmd in [approve, reject]
        ]
    )
    assert sorted(r.status_code for r in responses) == [200, 403]
    winner = [approve, reject][
        next(i for i, response in enumerate(responses) if response.status_code == 200)
    ]
    assert (
        await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=winner)
    ).status_code == 200
    async with sessions() as s:
        revision = await s.scalar(
            select(Revision).where(Revision.requisition_id == UUID(req["id"]))
        )
        assert (
            await s.scalar(
                select(func.count())
                .select_from(Decision)
                .where(Decision.revision_id == revision.id)
            )
            == 1
        )
        events = (
            await s.scalars(
                select(AuditEvent).where(
                    AuditEvent.resource_id == UUID(req["id"]),
                    AuditEvent.action.in_(["requisition.approved", "requisition.rejected"]),
                )
            )
        ).all()
        assert len(events) == 1
        assert (
            await s.scalar(
                select(func.count())
                .select_from(OutboxItem)
                .where(
                    OutboxItem.event_id == events[0].id,
                    OutboxItem.destination == "requisition_notification",
                )
            )
            == 1
        )


async def test_decision_audit_failure_rolls_back_everything(
    context, organisation, sessions, monkeypatch
):
    client, _, _ = context
    req = await pending(client, organisation)
    await sign_in(client, organisation["people"]["hod"])
    cmd = await command_for(client, req, organisation["people"]["hod"], "approve")
    from app.requisitions import router

    original = router.record_event

    async def fail(*args, **kwargs):
        if kwargs.get("action") == "requisition.approved":
            raise SQLAlchemyError("Synthetic audit failure")
        return await original(*args, **kwargs)

    monkeypatch.setattr(router, "record_event", fail)
    response = await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=cmd)
    assert response.status_code == 503
    async with sessions() as s:
        assert (await s.get(Requisition, UUID(req["id"]))).state == "PENDING_AUTHORITY"
        assert not (await s.get(SigningChallenge, UUID(cmd["challenge_id"]))).consumed
    monkeypatch.setattr(router, "record_event", original)
    assert (
        await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=cmd)
    ).status_code == 200


async def test_correction_snapshots_and_private_evidence_survive_resubmission(
    context, organisation, sessions
):
    client, _, _ = context
    people = organisation["people"]
    await sign_in(client, people["staff"])
    req = await draft(client, organisation, "4000000")
    file = (await upload(client, req)).json()
    req = (await client.get(f"/api/v1/requisitions/{req['id']}")).json()
    req, _ = await signed(client, req, people["staff"], "submit")
    await sign_in(client, people["hod"])
    req, cmd = await signed(
        client, req, people["hod"], "return", "Include delivery and updated quotation."
    )
    assert (
        await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=cmd)
    ).status_code == 200
    await sign_in(client, people["staff"])
    path = f"/api/v1/requisitions/{req['id']}"
    assert (
        await client.put(
            path + "/draft",
            json={"expected_version": req["version"], "content": content("8000000")},
        )
    ).status_code == 403
    start = {"expected_version": req["version"], "idempotency_key": str(uuid4())}
    req = (await client.post(path + "/revisions", json=start)).json()
    assert req["state"] == "DRAFT" and req["revision_number"] == 1
    assert (await client.post(path + "/revisions", json=start)).json()["version"] == req["version"]
    assert (
        await client.delete(
            "/api/v1/attachments/" + file["id"], params={"expected_version": req["version"]}
        )
    ).status_code == 204
    assert (await client.get(path + "/attachments")).json()["items"] == []
    assert (await client.get(path + "/attachments?revision=1")).json()["items"][0]["id"] == file[
        "id"
    ]
    assert (await client.get("/api/v1/attachments/" + file["id"] + "/content")).content == png()
    req = (await client.get(path)).json()
    req = (
        await client.put(
            path + "/draft",
            json={"expected_version": req["version"], "content": content("8000000")},
        )
    ).json()
    replay = (await client.post(path + "/revisions", json=start)).json()
    assert replay["total"] == "4000000.00" and replay["version"] == start["expected_version"] + 1
    assert replay["available_actions"] == []
    assert (
        await client.post(path + "/revisions", json={**start, "expected_version": req["version"]})
    ).status_code == 409
    historic = (await client.get(path + "?revision=1")).json()
    assert historic["total"] == "4000000.00" and historic["available_actions"] == []
    await sign_in(client, people["hod"])
    assert (await client.get(path)).status_code == 404  # Unsent successor is private.
    await sign_in(client, people["staff"])
    req, _ = await signed(client, req, people["staff"], "submit")
    assert req["revision_number"] == 2 and req["required_authority"] == "chief_of_staff"
    assert (await client.get(path + "?revision=1")).json()["total"] == "4000000.00"
    assert (await client.get(path + "/attachments?revision=1")).json()["items"][0]["id"] == file[
        "id"
    ]
    assert (await client.get(path + "/attachments?revision=2")).json()["items"] == []
    await sign_in(client, people["chief_of_staff"])
    req, _ = await signed(client, req, people["chief_of_staff"], "approve")
    assert req["state"] == "APPROVED"
    async with sessions() as s:
        revisions = (
            await s.scalars(
                select(Revision)
                .where(Revision.requisition_id == UUID(req["id"]))
                .order_by(Revision.number)
            )
        ).all()
        assert len(revisions) == 2 and revisions[0].content["lines"][0]["unit_price"] == "4000000"
        assert revisions[0].signature["challenge_id"] != revisions[1].signature["challenge_id"]


async def test_board_tasks_are_separate_from_individual_decisions(context, organisation, sessions):
    client, _, _ = context
    req = await pending(client, organisation, "500000000.01")
    for role in ["hod", "chief_of_staff", "md", "secretary", "chairman"]:
        await sign_in(client, organisation["people"][role])
        assert (await client.get("/api/v1/approvals/inbox")).json()["total"] == (
            1 if role == "secretary" else 0
        )
        assert (
            await client.post(
                f"/api/v1/requisitions/{req['id']}/signing-challenges",
                json={"expected_version": req["version"], "action": "approve"},
            )
        ).status_code in {403, 404, 409}


async def test_expired_decision_challenge_and_same_evidence_resubmission(
    context, organisation, sessions
):
    client, _, _ = context
    people = organisation["people"]
    await sign_in(client, people["staff"])
    req = await draft(client, organisation, "20")
    file = (await upload(client, req)).json()
    path = f"/api/v1/requisitions/{req['id']}"
    req = (await client.get(path)).json()
    req, _ = await signed(client, req, people["staff"], "submit")
    await sign_in(client, people["hod"])
    cmd = await command_for(client, req, people["hod"], "approve")
    async with sessions() as s, s.begin():
        await s.execute(
            update(SigningChallenge)
            .where(SigningChallenge.id == UUID(cmd["challenge_id"]))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    response = await client.post(path + "/actions", json=cmd)
    assert response.status_code == 409 and response.json()["code"] == "SIGNATURE_INVALID"
    req, _ = await signed(client, req, people["hod"], "return", "Clarify the location.")
    await sign_in(client, people["staff"])
    req = (
        await client.post(
            path + "/revisions",
            json={"expected_version": req["version"], "idempotency_key": str(uuid4())},
        )
    ).json()
    data = content("20")
    data["location"] = "Updated location"
    req = (
        await client.put(
            path + "/draft", json={"expected_version": req["version"], "content": data}
        )
    ).json()
    req, _ = await signed(client, req, people["staff"], "submit")
    assert req["revision_number"] == 2
    for number in [1, 2]:
        assert (await client.get(path + f"/attachments?revision={number}")).json()["items"][0][
            "id"
        ] == file["id"]
    assert (await client.get(path + "?revision=1")).json()["content"]["location"] == "Abuja"
    assert (await client.get(path + "?revision=2")).json()["content"][
        "location"
    ] == "Updated location"


async def test_replacement_officeholder_cannot_inherit_assigned_request(
    context, organisation, sessions
):
    client, _, _ = context
    people = organisation["people"]
    req = await pending(client, organisation)
    async with sessions() as s, s.begin():
        office = await s.scalar(select(Office).where(Office.identity_id == people["hod"]["id"]))
        office.active = False
        await s.flush()
        s.add(
            Office(
                identity_id=people["chief_of_staff"]["id"],
                entity_id=office.entity_id,
                department_id=office.department_id,
                role="hod",
                valid_from=datetime.now(UTC),
                authorisation_reference="Synthetic replacement appointment",
            )
        )
    await sign_in(client, people["chief_of_staff"])
    assert (await client.get("/api/v1/approvals/inbox")).json()["total"] == 0
    assert (await client.get(f"/api/v1/requisitions/{req['id']}")).status_code == 404
    await sign_in(client, people["staff"])
    detail = (await client.get(f"/api/v1/requisitions/{req['id']}")).json()
    assert "no longer holds" in detail["decision_blocker"]
    assert detail["available_actions"] == []


async def test_inbox_navigation_uses_office_not_queue_or_admin_permissions(
    context, organisation, sessions
):
    client, _, _ = context
    people = organisation["people"]
    for role, person in people.items():
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": person["email"], "password": "Synthetic-test-password-2026"},
        )
        assert response.status_code == 200
        expected = role in {"hod", "other_hod", "chief_of_staff", "md", "secretary", "chairman"}
        assert response.json()["can_access_approval_inbox"] is expected
        assert (await client.get("/api/v1/auth/me")).json()["can_access_approval_inbox"] is expected
        assert (await client.get("/api/v1/approvals/inbox")).json()["total"] == 0
    async with sessions() as s, s.begin():
        await s.execute(
            update(Account)
            .where(Account.identity_id == people["staff"]["id"])
            .values(permissions=["staff:manage", "organisation:manage", "office_assignment:manage"])
        )
    await sign_in(client, people["staff"])
    assert not (await client.get("/api/v1/auth/me")).json()["can_access_approval_inbox"]


async def test_inbox_navigation_rechecks_effective_appointment(context, organisation, sessions):
    from app.organisation.models import Department, Entity, Membership

    client, _, _ = context
    person = organisation["people"]["hod"]
    await sign_in(client, person)
    async with sessions() as s:
        office = await s.scalar(select(Office).where(Office.identity_id == person["id"]))
        office_id, dept_id, entity_id = office.id, office.department_id, office.entity_id
        member = await s.scalar(select(Membership).where(Membership.identity_id == person["id"]))
        member_id = member.id
        other = await s.scalar(
            select(Department).where(Department.entity_id == entity_id, Department.id != dept_id)
        )
        other_id = other.id
    now = datetime.now(UTC)
    changes = [
        (Office, office_id, {"active": False}, {"active": True}),
        (
            Office,
            office_id,
            {"valid_until": now - timedelta(seconds=1), "valid_from": now - timedelta(days=1)},
            {"valid_until": None},
        ),
        (
            Office,
            office_id,
            {"valid_from": now + timedelta(days=1)},
            {"valid_from": now - timedelta(days=1)},
        ),
        (Membership, member_id, {"active": False}, {"active": True}),
        (Membership, member_id, {"department_id": other_id}, {"department_id": dept_id}),
        (Department, dept_id, {"active": False}, {"active": True}),
        (Entity, entity_id, {"active": False}, {"active": True}),
    ]
    for model, record_id, change, restore in changes:
        async with sessions() as s, s.begin():
            await s.execute(update(model).where(model.id == record_id).values(**change))
        assert not (await client.get("/api/v1/auth/me")).json()["can_access_approval_inbox"], (
            model,
            change,
        )
        async with sessions() as s, s.begin():
            await s.execute(update(model).where(model.id == record_id).values(**restore))
        assert (await client.get("/api/v1/auth/me")).json()["can_access_approval_inbox"]
    async with sessions() as s, s.begin():
        await s.execute(
            update(Account).where(Account.identity_id == person["id"]).values(read_only=True)
        )
    assert not (await client.get("/api/v1/auth/me")).json()["can_access_approval_inbox"]
