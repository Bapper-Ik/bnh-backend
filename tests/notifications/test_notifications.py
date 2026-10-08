import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.audit.models import AuditEvent, OutboxItem
from app.identity.models import Account
from app.notifications.delivery import DeliveryFailure, claim_email, deliver_claim
from app.notifications.models import Notification
from app.notifications.service import materialize_one, project
from app.organisation.models import Office
from tests.board.test_board import act, setup
from tests.requisitions.test_creation import context as context
from tests.requisitions.test_workflow import content, draft, sign_in, signed
from tests.requisitions.test_workflow import organisation as organisation


@pytest.fixture
def mail(settings):
    return settings.model_copy(
        update={
            "mail_enabled": True,
            "mail_from": "custodian@example.com",
            "resend_api_key": SecretStr("synthetic-key"),
        }
    )


async def project_request(sessions, settings, req):
    async with sessions() as s, s.begin():
        jobs = (
            await s.scalars(
                select(OutboxItem)
                .join(AuditEvent)
                .where(
                    AuditEvent.resource_id == UUID(req["id"]),
                    OutboxItem.destination == "requisition_notification",
                )
                .order_by(OutboxItem.created_at, OutboxItem.id)
            )
        ).all()
        for job in jobs:
            if job.status == "pending":
                await project(s, settings, job)
        return list(
            (
                await s.scalars(
                    select(Notification).where(Notification.requisition_id == UUID(req["id"]))
                )
            ).all()
        )


async def submitted(context, organisation, amount="10"):
    client, _, _ = context
    staff = organisation["people"]["staff"]
    await sign_in(client, staff)
    req, _ = await signed(client, await draft(client, organisation, amount), staff, "submit")
    return req


async def page(client):
    r = await client.get("/api/v1/notifications")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize(
    "amount,role", [("10", "hod"), ("6000000", "chief_of_staff"), ("100000001", "md")]
)
async def test_recipient_scope_read_and_dedup(
    context, organisation, sessions, settings, amount, role
):
    client, _, _ = context
    people = organisation["people"]
    req = await submitted(context, organisation, amount)
    rows = await project_request(sessions, settings, req)
    assert len(rows) == 2
    assert {r.recipient_id for r in rows} == {people["staff"]["id"], people[role]["id"]}
    assert all(r.email_status == "disabled" for r in rows)
    assert await claim_email(sessions, settings, rows[0].id) is None
    from scripts.notification_status import snapshot

    async with sessions() as s:
        diagnostics = await snapshot(s)
        assert any(group["status"] == "disabled" for group in diagnostics["email"])
        assert "@example.com" not in str(diagnostics)
        assert req["reference"] not in str(diagnostics)
    async with sessions() as s, s.begin():
        job = await s.scalar(
            select(OutboxItem).where(
                OutboxItem.event_id == rows[0].event_id,
                OutboxItem.destination == "requisition_notification",
            )
        )
        await project(s, settings, job)
        assert (
            await s.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.requisition_id == UUID(req["id"]))
            )
            == 2
        )
    own = await page(client)
    assert own["total"] == own["unread_total"] == 1
    assert not own["email_enabled"]
    assert "recipient_address" not in str(own) and "strokes" not in str(own)
    other = next(r for r in rows if r.recipient_id == people[role]["id"])
    assert (await client.post(f"/api/v1/notifications/{other.id}/read")).status_code == 404
    own_id = own["items"][0]["id"]
    token = client.headers.pop("x-csrf-token")
    assert (await client.post(f"/api/v1/notifications/{own_id}/read")).status_code == 403
    client.headers["x-csrf-token"] = token
    first = await client.post(f"/api/v1/notifications/{own_id}/read")
    second = await client.post(f"/api/v1/notifications/{own_id}/read")
    assert first.status_code == 200 and first.json()["read_at"] == second.json()["read_at"]
    assert (await page(client))["unread_total"] == 0
    assert (await client.get("/api/v1/notifications?unread=true")).json()["total"] == 0
    assert (await client.get(f"/api/v1/requisitions/{req['id']}")).json()[
        "state"
    ] == "PENDING_AUTHORITY"
    async with sessions() as s:
        assert (
            await s.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.resource_id == UUID(req["id"]),
                    AuditEvent.action == "notification.read.success",
                )
            )
            == 1
        )
    await sign_in(client, people["other_hod"])
    assert (await page(client))["total"] == 0
    await sign_in(client, people[role])
    assert (await page(client))["items"][0]["href"] == f"/requisitions/{req['id']}"
    client.cookies.clear()
    assert (await client.get("/api/v1/notifications")).status_code == 401
    async with sessions() as s:
        audit = await s.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_id == UUID(req["id"]),
                AuditEvent.action == "notification.read.success",
            )
        )
        assert audit.entity_id == UUID(organisation["entity_id"])
    async with sessions() as s, s.begin():
        account = await s.scalar(
            select(Account).where(Account.identity_id == people["staff"]["id"])
        )
        account.permissions = ["audit:read"]
    await sign_in(client, people["staff"])
    audit_page = await client.get(
        "/api/v1/audit-events",
        params={
            "search": req["reference"],
            "action": "notification.read.success",
        },
    )
    assert audit_page.status_code == 200 and audit_page.json()["total"] == 1


async def test_return_resubmit_cancels_old_task_and_routes_new_amount(
    context, organisation, sessions, mail
):
    client, _, _ = context
    p = organisation["people"]
    req = await submitted(context, organisation)
    rows = await project_request(sessions, mail, req)
    old = next(r for r in rows if r.kind == "approval_task")
    await sign_in(client, p["hod"])
    req, _ = await signed(client, req, p["hod"], "return", "Add delivery")
    await project_request(sessions, mail, req)
    assert (await page(client))["total"] == 0
    await sign_in(client, p["staff"])
    assert (await page(client))["total"] == 2
    path = f"/api/v1/requisitions/{req['id']}"
    rev = await client.post(
        path + "/revisions",
        json={"expected_version": req["version"], "idempotency_key": str(uuid4())},
    )
    changed = await client.put(
        path + "/draft",
        json={"expected_version": rev.json()["version"], "content": content("6000000")},
    )
    req, _ = await signed(client, changed.json(), p["staff"], "submit")
    await project_request(sessions, mail, req)
    all_items = (await page(client))["items"]
    assert {i["title"] for i in all_items} == {
        "Requisition submitted",
        "Requisition returned for revision",
        "Requisition resubmitted",
    }
    assert (await client.get("/api/v1/notifications?limit=1&offset=1")).json()["total"] == 3
    called = []

    async def send(*args):
        called.append(args)
        return uuid4()

    claim = await claim_email(sessions, mail, old.id)
    await deliver_claim(sessions, mail, claim, send)
    assert not called
    async with sessions() as s:
        assert (await s.get(Notification, old.id)).email_status == "cancelled"
    await sign_in(client, p["chief_of_staff"])
    assert (await page(client))["total"] == 1
    await sign_in(client, p["hod"])
    assert (await page(client))["total"] == 0


@pytest.mark.parametrize(
    "outcome,title,hold",
    [
        ("APPROVE", "Board approval confirmed", False),
        ("REJECT", "Board rejection confirmed", False),
        ("DEFER", "Board deferment confirmed", True),
        ("CONDITIONAL_APPROVE", "Conditional Board approval confirmed — on hold", True),
    ],
)
async def test_board_recipients_and_actual_outcome(
    context, organisation, sessions, settings, outcome, title, hold
):
    client, _, _ = context
    p = organisation["people"]
    case = await setup(client, organisation, outcome)
    await project_request(sessions, settings, case["request"])
    assert (await page(client))["items"][0]["title"] == "Board resolution needs recording"
    case, _, _ = await act(client, case, p["secretary"], "board_submit")
    await project_request(sessions, settings, case["request"])
    assert (await page(client))["total"] == 0
    await sign_in(client, p["chairman"])
    alert = (await page(client))["items"][0]
    assert alert["title"] == "Board record needs your review" and alert["href"].endswith("/board")
    case, _, _ = await act(client, case, p["chairman"], "board_confirm")
    await project_request(sessions, settings, case["request"])
    assert (await page(client))["total"] == 0
    await sign_in(client, p["staff"])
    alerts = await page(client)
    assert title in {i["title"] for i in alerts["items"]}
    assert all(not i["href"].endswith("/board") for i in alerts["items"])
    assert "attendance" not in str(alerts) and "meeting_date" not in str(alerts)
    await sign_in(client, p["secretary"])
    alerts = await page(client)
    assert alerts["total"] == int(hold)
    if hold:
        assert alerts["items"][0]["title"] == "Later Board resolution required — hold remains"


async def test_board_correction_and_counterpart_revocation(context, organisation, sessions, mail):
    client, _, _ = context
    p = organisation["people"]
    case = await setup(client, organisation)
    await project_request(sessions, mail, case["request"])
    case, _, _ = await act(client, case, p["secretary"], "board_submit")
    rows = await project_request(sessions, mail, case["request"])
    chairman = next(r for r in rows if r.kind == "board_signoff_task")
    await sign_in(client, p["chairman"])
    assert (await page(client))["total"] == 1
    async with sessions() as s, s.begin():
        office = await s.scalar(select(Office).where(Office.identity_id == p["secretary"]["id"]))
        office.active = False
    assert (await page(client))["total"] == 0

    async def must_not_send(*args):
        pytest.fail("Revoked counterpart must prevent Board email")

    await deliver_claim(
        sessions, mail, await claim_email(sessions, mail, chairman.id), must_not_send
    )
    async with sessions() as s, s.begin():
        assert (await s.get(Notification, chairman.id)).email_status == "cancelled"
        office = await s.scalar(select(Office).where(Office.identity_id == p["secretary"]["id"]))
        office.active = True
    case, _, _ = await act(client, case, p["chairman"], "board_return", "Correct meeting reference")
    await project_request(sessions, mail, case["request"])
    await sign_in(client, p["secretary"])
    assert (await page(client))["items"][0]["title"] == "Board record returned for correction"
    await sign_in(client, p["staff"])
    assert [i["title"] for i in (await page(client))["items"]] == ["Requisition submitted"]


async def test_transaction_rollback_concurrent_projection_and_retries(
    context, organisation, sessions, mail, monkeypatch
):
    req = await submitted(context, organisation)
    async with sessions() as s:
        job = await s.scalar(
            select(OutboxItem)
            .join(AuditEvent)
            .where(
                AuditEvent.resource_id == UUID(req["id"]),
                OutboxItem.destination == "requisition_notification",
            )
        )
        event_id, job_id = job.event_id, job.id
    with pytest.raises(RuntimeError):
        async with sessions() as s, s.begin():
            assert await materialize_one(s, mail, event_id)
            raise RuntimeError("Simulated restart before commit")
    async with sessions() as s:
        assert (await s.get(OutboxItem, job_id)).status == "pending"
        assert not await s.scalar(select(Notification.id).where(Notification.event_id == event_id))

    async def broken(*args):
        await project(*args)
        raise RuntimeError("Sensitive provider details must never be logged")

    with monkeypatch.context() as patch:
        patch.setattr("app.notifications.service.project", broken)
        async with sessions() as s, s.begin():
            assert await materialize_one(s, mail, event_id)
    async with sessions() as s, s.begin():
        job = await s.get(OutboxItem, job_id)
        assert job.status == "pending" and job.attempts == 1
        assert job.available_at > datetime.now(UTC)
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)

    async def run():
        async with sessions() as s, s.begin():
            return await materialize_one(s, mail, event_id)

    assert sorted(await asyncio.gather(run(), run())) == [False, True]
    async with sessions() as s:
        assert (
            await s.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.event_id == event_id)
            )
            == 2
        )
        assert (await s.get(OutboxItem, job_id)).status == "delivered"


@pytest.mark.parametrize("change", ["inactive", "email", "office", "origin"])
async def test_delivery_revalidates_recipient(context, organisation, sessions, mail, change):
    req = await submitted(context, organisation)
    row = next(r for r in await project_request(sessions, mail, req) if r.kind == "approval_task")
    claim = await claim_email(sessions, mail, row.id)
    async with sessions() as s, s.begin():
        account = await s.scalar(select(Account).where(Account.identity_id == row.recipient_id))
        if change == "inactive":
            account.active = False
        if change == "email":
            account.email = f"changed-{uuid4()}@example.com"
        if change == "office":
            (
                await s.scalar(select(Office).where(Office.identity_id == row.recipient_id))
            ).active = False
    if change == "origin":
        mail = mail.model_copy(update={"frontend_origin": "https://changed.example.com"})

    async def must_not_send(*args):
        pytest.fail("Invalidated recipient must not receive email")

    await deliver_claim(sessions, mail, claim, must_not_send)
    async with sessions() as s:
        assert (await s.get(Notification, row.id)).email_status == "cancelled"


async def test_email_failure_retry_lease_recovery_and_bounded_window(
    context, organisation, sessions, mail
):
    client, _, _ = context
    req = await submitted(context, organisation)
    row = next(r for r in await project_request(sessions, mail, req) if r.kind == "request_update")
    claim = await claim_email(sessions, mail, row.id)
    assert await claim_email(sessions, mail, row.id) is None
    calls = []

    async def temporary(settings, notification, reference):
        calls.append(
            (notification.id, notification.recipient_address, notification.first_attempt_at)
        )
        raise DeliveryFailure("provider_rate_limit", retry_after=120)

    await deliver_claim(sessions, mail, claim, temporary)
    assert (await page(client))["total"] == 1
    async with sessions() as s, s.begin():
        stored = await s.get(Notification, row.id)
        assert stored.email_status == "pending" and stored.attempts == 1
        assert stored.available_at > datetime.now(UTC) + timedelta(seconds=100)
        stored.available_at = datetime.now(UTC) - timedelta(seconds=1)
    claim = await claim_email(sessions, mail, row.id)
    # Process dies after claiming; expired lease resumes with same frozen envelope.
    async with sessions() as s, s.begin():
        (await s.get(Notification, row.id)).lease_until = datetime.now(UTC) - timedelta(seconds=1)
    recovered = await claim_email(sessions, mail, row.id)
    assert recovered[1] != claim[1]
    provider = uuid4()

    async def accepted(settings, notification, reference):
        calls.append(
            (notification.id, notification.recipient_address, notification.first_attempt_at)
        )
        return provider

    await deliver_claim(sessions, mail, claim, accepted)
    assert len(calls) == 1
    await deliver_claim(sessions, mail, recovered, accepted)
    assert calls[0] == calls[1]
    async with sessions() as s, s.begin():
        stored = await s.get(Notification, row.id)
        assert (
            stored.email_status == "accepted"
            and stored.provider_id == provider
            and stored.attempts == 3
        )
        stored.email_status = "pending"
        stored.available_at = datetime.now(UTC) - timedelta(seconds=1)
        stored.first_attempt_at = datetime.now(UTC) - timedelta(hours=23)
    await deliver_claim(sessions, mail, await claim_email(sessions, mail, row.id), accepted)
    assert len(calls) == 2
    async with sessions() as s:
        stored = await s.get(Notification, row.id)
        assert stored.email_status == "failed" and stored.last_error == "retry_window_exhausted"


@pytest.mark.parametrize("permanent", [True, False])
async def test_failed_email_does_not_remove_task(context, organisation, sessions, mail, permanent):
    client, _, _ = context
    req = await submitted(context, organisation)
    row = next(r for r in await project_request(sessions, mail, req) if r.kind == "approval_task")

    async def fail(*args):
        raise DeliveryFailure("provider_rejected", retryable=not permanent)

    for _attempt in range(1, 2 if permanent else 7):
        async with sessions() as s, s.begin():
            (await s.get(Notification, row.id)).available_at = datetime.now(UTC) - timedelta(
                seconds=1
            )
        await deliver_claim(sessions, mail, await claim_email(sessions, mail, row.id), fail)
    async with sessions() as s:
        assert (await s.get(Notification, row.id)).email_status == "failed"
        assert (await s.get(Notification, row.id)).attempts == (1 if permanent else 6)
    await sign_in(client, organisation["people"]["hod"])
    assert (await page(client))["total"] == 1
    assert (await client.get("/api/v1/approvals/inbox")).json()["total"] == 1
    req, _ = await signed(client, req, organisation["people"]["hod"], "approve")
    assert req["state"] == "APPROVED"


async def test_worker_restart_recovers_persisted_lease(
    context, organisation, sessions, mail, monkeypatch
):
    from app.notifications.delivery import delivery_loop

    req = await submitted(context, organisation)
    row = next(r for r in await project_request(sessions, mail, req) if r.kind == "approval_task")
    original_claim = claim_email

    async def only_this_job(sessions, settings):
        return await original_claim(sessions, settings, row.id)

    async def projected(*args):
        return False

    monkeypatch.setattr("app.notifications.delivery.claim_email", only_this_job)
    monkeypatch.setattr("app.notifications.delivery.materialize_one", projected)
    started = asyncio.Event()
    envelopes = []

    async def interrupted(settings, notification, reference):
        envelopes.append((notification.id, notification.recipient_address, reference))
        started.set()
        await asyncio.Event().wait()

    worker = asyncio.create_task(delivery_loop(sessions, mail, interrupted))
    await asyncio.wait_for(started.wait(), 10)
    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker
    async with sessions() as s, s.begin():
        stored = await s.get(Notification, row.id)
        assert stored.email_status == "sending" and stored.first_attempt_at
        stored.lease_until = datetime.now(UTC) - timedelta(seconds=1)

    async def accepted(settings, notification, reference):
        envelopes.append((notification.id, notification.recipient_address, reference))
        return uuid4()

    worker = asyncio.create_task(delivery_loop(sessions, mail, accepted))
    try:
        async with asyncio.timeout(10):
            while True:
                async with sessions() as s:
                    if (await s.get(Notification, row.id)).email_status == "accepted":
                        break
                await asyncio.sleep(0.05)
    finally:
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker
    assert len(envelopes) == 2 and envelopes[0] == envelopes[1]
    async with sessions() as s:
        assert (
            await s.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.requisition_id == UUID(req["id"]))
            )
            == 2
        )


async def test_historical_backlog_creates_alerts_without_sending_old_email(
    context, organisation, sessions, mail, monkeypatch
):
    req = await submitted(context, organisation)

    class FutureClock:
        @staticmethod
        def now(zone):
            return datetime.now(zone) + timedelta(hours=25)

    monkeypatch.setattr("app.notifications.service.datetime", FutureClock)
    rows = await project_request(sessions, mail, req)
    assert len(rows) == 2
    assert all(r.email_status == "skipped" and r.last_error == "historical_event" for r in rows)
    assert await claim_email(sessions, mail, rows[0].id) is None
    assert (await page(context[0]))["total"] == 1
