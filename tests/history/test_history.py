from datetime import datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.access.models import ReviewGrant
from app.audit.models import AuditEvent
from app.core.database import Identity
from app.identity.models import Account
from app.organisation.models import Office
from app.requisitions.models import Decision, Revision
from tests.board.test_board import act, setup
from tests.requisitions.test_creation import context as context
from tests.requisitions.test_creation import upload
from tests.requisitions.test_workflow import content, draft, sign_in, signed
from tests.requisitions.test_workflow import organisation as organisation


async def audit_access(sessions, person, entity_id=None):
    async with sessions() as s, s.begin():
        account = await s.scalar(select(Account).where(Account.identity_id == person["id"]))
        account.permissions = ["audit:read"]
        if entity_id:
            account.read_only = True
            s.add(ReviewGrant(identity_id=person["id"], entity_id=UUID(entity_id)))


async def test_timeline_paginates_actual_events_and_preserves_signed_names(
    context, organisation, sessions
):
    client, _, _ = context
    p = organisation["people"]
    await sign_in(client, p["staff"])
    req = await draft(client, organisation, "10")
    path = f"/api/v1/requisitions/{req['id']}"
    req, _ = await signed(client, req, p["staff"], "submit")
    assert req["next_action"]["actor_name"] == p["hod"]["name"]
    await sign_in(client, p["hod"])
    req, _ = await signed(client, req, p["hod"], "return", "Add delivery")
    await sign_in(client, p["staff"])
    response = await client.post(
        path + "/revisions",
        json={"expected_version": req["version"], "idempotency_key": str(uuid4())},
    )
    response = await client.put(
        path + "/draft",
        json={"expected_version": response.json()["version"], "content": content("6000000")},
    )
    req, _ = await signed(client, response.json(), p["staff"], "submit")
    async with sessions() as s, s.begin():
        (await s.get(Identity, p["hod"]["id"])).display_name = "Renamed current HOD"
    items = []
    for offset in range(0, 6, 2):
        result = await client.get(path + "/history", params={"limit": 2, "offset": offset})
        assert result.status_code == 200, result.text
        assert result.json()["total"] == 6
        items.extend(result.json()["items"])
    assert len({x["id"] for x in items}) == 6
    assert [x["at"] for x in items] == sorted(x["at"] for x in items)
    assert [x["type"] for x in items] == [
        "requisition.created",
        "submission",
        "return",
        "requisition.revision_created",
        "requisition.updated",
        "submission",
    ]
    decision = next(x for x in items if x["type"] == "return")
    assert decision["actor"] == p["hod"]["name"] and decision["signature_id"] and decision["digest"]
    assert "strokes" not in str(items)
    assert req["next_action"]["actor_name"] == p["chief_of_staff"]["name"]
    only_revision = (await client.get(path + "/history?revision=1")).json()
    assert [x["type"] for x in only_revision["items"]] == ["submission", "return"]
    async with sessions() as s:
        assert (
            len(
                (
                    await s.scalars(
                        select(Revision).where(Revision.requisition_id == UUID(req["id"]))
                    )
                ).all()
            )
            == 2
        )
        assert (
            len(
                (
                    await s.scalars(
                        select(Decision)
                        .join(Revision)
                        .where(Revision.requisition_id == UUID(req["id"]))
                    )
                ).all()
            )
            == 1
        )
        assert await s.scalar(
            select(AuditEvent.id).where(
                AuditEvent.resource_id == UUID(req["id"]),
                AuditEvent.action == "requisition.history_view.success",
            )
        )
    await sign_in(client, p["hod"])
    assert (await client.get(path + "/history")).status_code == 404
    async with sessions() as s:
        assert await s.scalar(
            select(AuditEvent.id).where(
                AuditEvent.action == "requisition.history_view.failure",
                AuditEvent.actor_id == p["hod"]["id"],
            )
        )


async def test_search_filters_scope_dates_and_literal_wildcards(context, organisation, sessions):
    client, _, _ = context
    p = organisation["people"]
    await sign_in(client, p["staff"])
    req = await draft(client, organisation, "10")
    local_day = (
        datetime.fromisoformat(req["created_at"])
        .astimezone(ZoneInfo("Africa/Lagos"))
        .date()
        .isoformat()
    )
    params = {
        "requester": "staff",
        "department": "Operations",
        "company": "Synthetic company",
        "vendor": "Synthetic supplier",
        "state": "DRAFT",
        "date_from": local_day,
        "date_to": local_day,
        "my_requests": "true",
        "limit": 1,
    }
    result = await client.get("/api/v1/requisitions", params=params)
    assert result.status_code == 200, result.text
    assert result.json()["total"] == 1 and result.json()["items"][0]["id"] == req["id"]
    for key in ["requester", "department", "company", "vendor"]:
        assert (await client.get("/api/v1/requisitions", params={key: "%"})).json()["total"] == 0
    assert (
        await client.get("/api/v1/requisitions?date_from=2026-02-01&date_to=2026-01-01")
    ).status_code == 422
    await sign_in(client, p["other_hod"])
    assert (await client.get("/api/v1/requisitions", params=params)).json()["total"] == 0
    assert (await client.get(f"/api/v1/requisitions/{req['id']}/history")).status_code == 404
    await audit_access(sessions, p["other_hod"])
    assert (await client.get("/api/v1/audit-events", params={"search": req["reference"]})).json()[
        "total"
    ] == 0


async def test_audit_permission_scope_snapshot_and_evidence_link(context, organisation, sessions):
    client, _, _ = context
    p = organisation["people"]
    await sign_in(client, p["staff"])
    req = await draft(client, organisation, "10")
    file = (await upload(client, req)).json()
    assert (await client.get("/api/v1/audit-events")).status_code == 403
    async with sessions() as s:
        assert await s.scalar(
            select(AuditEvent.id).where(
                AuditEvent.action == "audit.search.failure", AuditEvent.actor_id == p["staff"]["id"]
            )
        )
    await audit_access(sessions, p["staff"])
    response = await client.get(
        "/api/v1/audit-events", params={"search": req["reference"], "limit": 1}
    )
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 2
    assert page["items"][0]["attachment_id"] == file["id"]
    assert "storage_key" not in response.text and "event_key" not in response.text
    assert "details" not in response.text and "strokes" not in response.text
    second = await client.get(
        "/api/v1/audit-events",
        params={"search": req["reference"], "limit": 1, "offset": 1, "before": page["before"]},
    )
    assert (
        second.json()["total"] == 2 and second.json()["items"][0]["action"] == "requisition.created"
    )
    assert (
        await client.get(
            "/api/v1/audit-events",
            params={
                "search": req["reference"],
                "action": "evidence.uploaded",
                "actor": "staff",
                "company": "Synthetic",
            },
        )
    ).json()["total"] == 1
    assert (await client.get("/api/v1/audit-events?before=2026-01-01T12:00:00")).status_code == 422
    for method in [client.post, client.patch, client.delete]:
        assert (await method("/api/v1/audit-events")).status_code == 405
    await sign_in(client, p["other_hod"])
    await audit_access(sessions, p["other_hod"], organisation["entity_id"])
    assert (await client.get("/api/v1/audit-events", params={"search": req["reference"]})).json()[
        "total"
    ] == 2
    async with sessions() as s, s.begin():
        grant = await s.scalar(
            select(ReviewGrant).where(ReviewGrant.identity_id == p["other_hod"]["id"])
        )
        grant.active = False
    assert (await client.get("/api/v1/audit-events", params={"search": req["reference"]})).json()[
        "total"
    ] == 0


async def test_board_history_keeps_private_records_out_of_requester_timeline_and_audit(
    context, organisation, sessions
):
    client, _, _ = context
    p = organisation["people"]
    case = await setup(client, organisation, outcome="DEFER")
    await audit_access(sessions, p["secretary"])
    case, _, _ = await act(client, case, p["secretary"], "board_submit")
    path = f"/api/v1/requisitions/{case['request']['id']}"
    assert case["request"]["next_action"]["actor_name"] == p["chairman"]["name"]
    private = (await client.get(path + "/history")).json()
    record = next(x for x in private["items"] if x["type"] == "board_submitted")
    assert (
        record["meeting_date"] == "2026-01-01" and record["evidence_id"] and record["signature_id"]
    )
    assert record["at"][:10] != record["meeting_date"]
    assert any(x["type"] == "board_recorded" for x in private["items"])
    await sign_in(client, p["chairman"])
    case, _, _ = await act(client, case, p["chairman"], "board_confirm")
    await sign_in(client, p["staff"])
    await audit_access(sessions, p["staff"])
    public = (await client.get(path + "/history")).json()
    assert [x["type"] for x in public["items"]] == [
        "requisition.created",
        "submission",
        "board_defer",
    ]
    assert all(x["resolution_id"] is None and x["evidence_id"] is None for x in public["items"])
    audit = (
        await client.get("/api/v1/audit-events", params={"search": case["request"]["reference"]})
    ).json()
    board = [x for x in audit["items"] if x["action"].startswith("board.")]
    assert len(board) == 1 and board[0]["action"] == "board.confirmed"
    assert "SYN-001" not in str(audit) and "formal-resolution" not in str(audit)
    assert (await client.get(path)).json()["next_action"]["label"].startswith("Hold remains")
    async with sessions() as s, s.begin():
        office = await s.scalar(select(Office).where(Office.identity_id == p["secretary"]["id"]))
        office.active = False
    assert (await client.get(path)).json()["next_action"]["blocked_reason"]


async def test_detachment_keeps_audit_history_but_removes_download_link(
    context, organisation, sessions
):
    client, _, _ = context
    person = organisation["people"]["staff"]
    await sign_in(client, person)
    req = await draft(client, organisation, "10")
    file = (await upload(client, req)).json()
    req = (await client.get("/api/v1/requisitions/" + req["id"])).json()
    assert (
        await client.delete(
            "/api/v1/attachments/" + file["id"], params={"expected_version": req["version"]}
        )
    ).status_code == 204
    await audit_access(sessions, person)
    result = (await client.get("/api/v1/audit-events", params={"search": req["reference"]})).json()
    assert result["total"] == 3
    evidence = [row for row in result["items"] if row["action"].startswith("evidence.")]
    assert {row["action"] for row in evidence} == {"evidence.uploaded", "evidence.detached"}
    assert all(row["request_id"] == req["id"] and row["attachment_id"] is None for row in evidence)
    assert (await client.get("/api/v1/access/attachments/" + file["id"])).status_code == 404
    for query in ("date_from=0001-01-01", "date_to=9999-12-31"):
        assert (await client.get("/api/v1/audit-events?" + query)).status_code == 422
        assert (await client.get("/api/v1/requisitions?" + query)).status_code == 422


async def test_controlled_audit_reviewer_provisioning_is_scoped_and_revocable(
    context, organisation, sessions
):
    import pytest

    from app.core.errors import DomainError
    from scripts.configure_audit_reviewer import configure

    client, _, _ = context
    p = organisation["people"]
    await sign_in(client, p["staff"])
    req = await draft(client, organisation, "10")
    entity_id = UUID(organisation["entity_id"])
    async with sessions() as s, s.begin():
        with pytest.raises(DomainError, match="Revoke financial appointments"):
            await configure(s, p["hod"]["email"], entity_id, True)
    async with sessions() as s, s.begin():
        office = await s.scalar(select(Office).where(Office.identity_id == p["other_hod"]["id"]))
        office.active = False
        await s.flush()
        await configure(s, p["other_hod"]["email"], entity_id, True)
    await sign_in(client, p["other_hod"])
    response = await client.get("/api/v1/audit-events", params={"search": req["reference"]})
    assert response.status_code == 200 and response.json()["total"] == 1
    assert (await client.get("/api/v1/requisitions/" + req["id"])).json()["available_actions"] == []
    async with sessions() as s, s.begin():
        await configure(s, p["other_hod"]["email"], entity_id, False)
    assert (await client.get("/api/v1/audit-events")).status_code == 403
    assert (await client.get("/api/v1/requisitions/" + req["id"])).status_code == 404
    async with sessions() as s:
        account = await s.scalar(select(Account).where(Account.identity_id == p["other_hod"]["id"]))
        assert account.read_only


async def test_board_counterpart_revocation_hides_private_audit_and_blocks_pending_actor(
    context, organisation, sessions
):
    client, _, _ = context
    p = organisation["people"]
    case = await setup(client, organisation)
    case, _, _ = await act(client, case, p["secretary"], "board_submit")
    await sign_in(client, p["chairman"])
    await audit_access(sessions, p["chairman"])
    params = {"search": case["request"]["reference"]}
    before = (await client.get("/api/v1/audit-events", params=params)).json()
    assert any(row["action"] == "board.recorded" for row in before["items"])
    async with sessions() as s, s.begin():
        office = await s.scalar(select(Office).where(Office.identity_id == p["secretary"]["id"]))
        office.active = False
    path = "/api/v1/requisitions/" + case["request"]["id"]
    req = (await client.get(path)).json()
    assert req["next_action"]["blocked_reason"] and req["next_action"]["actor_name"] is None
    audit = (await client.get("/api/v1/audit-events", params=params)).json()
    assert not any(row["action"].startswith("board.") for row in audit["items"])
    assert audit["total"] < before["total"]
    history = (await client.get(path + "/history")).json()
    assert [row["type"] for row in history["items"]] == ["requisition.created", "submission"]
