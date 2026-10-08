from sqlalchemy import select

from app.access.models import ReviewGrant
from app.identity.models import Account
from app.organisation.models import Membership, Office
from tests.requisitions.test_creation import context as context
from tests.requisitions.test_workflow import draft, sign_in, signed
from tests.requisitions.test_workflow import organisation as organisation


async def test_counts_match_scoped_lists_and_do_not_leak_other_departments(context, organisation):
    client, _, _ = context
    people = organisation["people"]
    assert (await client.get("/api/v1/dashboard")).status_code == 401
    await sign_in(client, people["staff"])
    req = await draft(client, organisation, "248000")
    result = await client.get("/api/v1/dashboard")
    assert result.status_code == 200, result.text
    view = result.json()
    assert result.headers["cache-control"] == "no-store"
    assert view["total"] == view["own_requests"] == 1
    assert view["counts"][0] == {"state": "DRAFT", "count": 1}
    assert view["activity"][0]["label"] == "Draft created"
    assert not view["can_access_approval_inbox"] and not view["tasks"]["items"]
    assert view["can_create"]
    req, _ = await signed(client, req, people["staff"], "submit")
    await sign_in(client, people["other_hod"])
    empty = (await client.get("/api/v1/dashboard")).json()
    assert empty["total"] == 0 and empty["activity"] == [] and empty["tasks"]["total"] == 0
    await sign_in(client, people["hod"])
    view = (await client.get("/api/v1/dashboard")).json()
    assert view["total"] == view["tasks"]["total"] == 1 and view["own_requests"] == 0
    assert view["tasks"]["items"][0]["id"] == req["id"]
    assert view["tasks"]["total"] == (await client.get("/api/v1/approvals/inbox")).json()["total"]
    req, _ = await signed(client, req, people["hod"], "return", "Update scope")
    assert (await client.get("/api/v1/dashboard")).json()["tasks"]["total"] == 0
    await sign_in(client, people["staff"])
    view = (await client.get("/api/v1/dashboard")).json()
    assert next(c["count"] for c in view["counts"] if c["state"] == "RETURNED_FOR_REVISION") == 1
    assert view["activity"][0]["label"] == "Returned for revision"
    assert all(set(e) == {"id", "request_id", "reference", "label", "at"} for e in view["activity"])


async def test_current_scope_readonly_and_technical_admin_limits(context, organisation, sessions):
    client, _, _ = context
    people = organisation["people"]
    await sign_in(client, people["staff"])
    req, _ = await signed(
        client, await draft(client, organisation, "100"), people["staff"], "submit"
    )
    await sign_in(client, people["hod"])
    assert (await client.get("/api/v1/dashboard")).json()["tasks"]["total"] == 1
    async with sessions() as s, s.begin():
        office = await s.scalar(select(Office).where(Office.identity_id == people["hod"]["id"]))
        office.active = False
        account = await s.scalar(select(Account).where(Account.identity_id == people["hod"]["id"]))
        account.permissions = ["staff:manage", "organisation:manage"]
    view = (await client.get("/api/v1/dashboard")).json()
    assert view["total"] == 0 and view["activity"] == [] and not view["can_access_approval_inbox"]
    async with sessions() as s, s.begin():
        account = await s.scalar(select(Account).where(Account.identity_id == people["hod"]["id"]))
        account.read_only = True
        s.add(
            ReviewGrant(
                identity_id=people["hod"]["id"], entity_id=organisation["entity_id"], active=True
            )
        )
    view = (await client.get("/api/v1/dashboard")).json()
    assert view["total"] == 1 and not view["can_create"] and view["tasks"]["total"] == 0
    assert "bank" not in str(view).lower() and "signature" not in str(view).lower()
    async with sessions() as s, s.begin():
        grant = await s.scalar(
            select(ReviewGrant).where(ReviewGrant.identity_id == people["hod"]["id"])
        )
        grant.active = False
    assert (await client.get("/api/v1/dashboard")).json()["total"] == 0
    await sign_in(client, people["staff"])
    async with sessions() as s, s.begin():
        member = await s.scalar(
            select(Membership).where(Membership.identity_id == people["staff"]["id"])
        )
        member.active = False
    view = (await client.get("/api/v1/dashboard")).json()
    assert view["total"] == 1 and not view["can_create"]


async def test_board_activity_and_tasks_follow_actual_handoff(context, organisation):
    from tests.board.test_board import act, setup

    client, _, _ = context
    people = organisation["people"]
    case = await setup(client, organisation, "DEFER")
    assert (await client.get("/api/v1/dashboard")).json()["tasks"]["total"] == 1
    case, _, _ = await act(client, case, people["secretary"], "board_submit")
    assert (await client.get("/api/v1/dashboard")).json()["tasks"]["total"] == 0
    await sign_in(client, people["staff"])
    assert all(
        not e["label"].startswith("Board")
        for e in (await client.get("/api/v1/dashboard")).json()["activity"]
    )
    await sign_in(client, people["chairman"])
    view = (await client.get("/api/v1/dashboard")).json()
    assert view["tasks"]["total"] == 1 and any(
        e["label"].startswith("Board") for e in view["activity"]
    )
    case, _, _ = await act(client, case, people["chairman"], "board_confirm")
    await sign_in(client, people["staff"])
    view = (await client.get("/api/v1/dashboard")).json()
    assert next(c["count"] for c in view["counts"] if c["state"] == "DEFERRED") == 1
    assert view["activity"][0]["label"] == "Board outcome confirmed"
    assert all("resolution_id" not in e for e in view["activity"])


async def test_dashboard_bounds_activity_and_requests(context, organisation):
    client, _, _ = context
    await sign_in(client, organisation["people"]["staff"])
    for _ in range(12):
        await draft(client, organisation, "1")
    view = (await client.get("/api/v1/dashboard")).json()
    assert view["total"] == view["own_requests"] == 12
    assert sum(c["count"] for c in view["counts"]) == 12
    assert len(view["activity"]) == 10 and len(view["recent_requests"]["items"]) == 5
    assert view["recent_requests"]["total"] == 12
