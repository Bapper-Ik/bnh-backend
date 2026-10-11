import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.errors import DomainError
from app.exports.models import Export
from app.exports.worker import claim_job, process_claim
from app.identity.models import Account
from tests.requisitions.test_workflow import content, draft, sign_in, signed


async def queue(client, req, **extra):
    command = {"expected_version": req["version"], "idempotency_key": str(uuid4()), **extra}
    response = await client.post(f"/api/v1/requisitions/{req['id']}/exports", json=command)
    assert response.status_code == 202, response.text
    return response.json(), command


async def generate(exports, sessions, item):
    _, app, storage = exports
    claim = await claim_job(sessions, UUID(item["id"]))
    assert claim
    await process_claim(sessions, app.state.settings, storage, claim)


@pytest.mark.parametrize("template", ["requisition-v1", "requisition-v2"])
async def test_persistent_draft_capture_idempotency_private_download(
    exports, organisation, sessions, monkeypatch, template
):
    monkeypatch.setattr("app.exports.service.TEMPLATE_VERSION", template)
    client, _, _ = exports
    await sign_in(client, organisation["people"]["staff"])
    req = await draft(client, organisation, "248000")
    item, command = await queue(client, req)
    path = f"/api/v1/requisitions/{req['id']}/exports"
    replies = await asyncio.gather(*[client.post(path, json=command) for _ in range(2)])
    assert {r.json()["id"] for r in replies} == {item["id"]}
    changed = {**command, "include_board": True}
    assert (await client.post(path, json=changed)).status_code == 409
    edited = await client.put(
        f"/api/v1/requisitions/{req['id']}/draft",
        json={"expected_version": req["version"], "content": content("24000000")},
    )
    assert edited.status_code == 200
    assert (
        await client.post(path, json={**command, "idempotency_key": str(uuid4())})
    ).status_code == 409
    await generate(exports, sessions, item)
    ready = (await client.get("/api/v1/exports/" + item["id"])).json()
    assert ready["status"] == "ready", ready
    assert ready["template_version"] == template
    response = await client.get("/api/v1/exports/" + item["id"] + "/content")
    assert response.status_code == 200 and response.content.startswith(b"%PDF-")
    import io

    from pypdf import PdfReader

    pdf_text = "".join(
        page.extract_text() for page in PdfReader(io.BytesIO(response.content)).pages
    )
    assert "SHA-256" not in pdf_text and "Signature reference" not in pdf_text
    assert (
        "Requisition and approval record" in pdf_text
        if template == "requisition-v1"
        else "Draft Requisition" in pdf_text
    )
    assert response.headers["cache-control"] == "no-store"
    assert hashlib.sha256(response.content).hexdigest() == ready["file_digest"]
    async with sessions() as s:
        row = await s.get(Export, UUID(item["id"]))
        assert row.snapshot["total"] == "248000.00"
        assert row.snapshot["state"] == "DRAFT" and row.snapshot["signatures"] == []
        assert row.font_version.startswith("bnh-liberation-v1:")
    assert (await client.get(path)).json()["total"] == 1
    for statement in [
        "UPDATE custodian.requisition_exports SET status='failed' WHERE id=:id",
        "UPDATE custodian.requisition_exports SET snapshot='{}' WHERE id=:id",
        "DELETE FROM custodian.requisition_exports WHERE id=:id",
    ]:
        with pytest.raises(DBAPIError):
            async with sessions() as s, s.begin():
                await s.execute(text(statement), {"id": UUID(item["id"])})
    await sign_in(client, organisation["people"]["other_hod"])
    assert (await client.get(path)).status_code == 404
    assert (await client.get("/api/v1/exports/" + item["id"] + "/content")).status_code == 404


@pytest.mark.parametrize(
    "action,state",
    [("approve", "APPROVED"), ("reject", "REJECTED"), ("return", "RETURNED_FOR_REVISION")],
)
async def test_signed_decisions_preserve_actual_records(
    exports, organisation, sessions, action, state
):
    client, _, _ = exports
    people = organisation["people"]
    await sign_in(client, people["staff"])
    req, _ = await signed(
        client, await draft(client, organisation, "123.45"), people["staff"], "submit"
    )
    await sign_in(client, people["hod"])
    req, _ = await signed(client, req, people["hod"], action, "Recorded decision reason")
    await sign_in(client, people["staff"])
    item, _ = await queue(client, req, revision=1)
    await generate(exports, sessions, item)
    async with sessions() as s:
        row = await s.get(Export, UUID(item["id"]))
        assert row.status == "ready", row.last_error
        assert row.snapshot["state"] == state
        assert len(row.snapshot["signatures"]) == 2
        assert all(
            record["strokes"] and record["at"] and record["digest"]
            for record in row.snapshot["signatures"]
        )
        assert row.snapshot["signatures"][1]["reason"] == "Recorded decision reason"
        assert row.generated_at > datetime.fromisoformat(row.snapshot["signatures"][1]["at"])


async def test_missing_and_wrong_fonts_never_fall_back(
    context, organisation, tmp_path, monkeypatch
):
    client, app, _ = context
    from app.exports import render as pdf_render

    monkeypatch.setattr(pdf_render, "FONT_DIRECTORY", tmp_path)
    await sign_in(client, organisation["people"]["staff"])
    req = await draft(client, organisation, "1")
    path = f"/api/v1/requisitions/{req['id']}/exports"
    assert "bundled PDF fonts" in (await client.get(path)).json()["unavailable_reason"]
    response = await client.post(
        path, json={"expected_version": req["version"], "idempotency_key": str(uuid4())}
    )
    assert response.status_code == 503
    from pathlib import Path

    import reportlab

    from app.exports.render import FONT_FILES, available

    for filename, _, _ in FONT_FILES.values():
        (tmp_path / filename).write_bytes(
            (Path(reportlab.__file__).parent / "fonts/Vera.ttf").read_bytes()
        )
    assert not available()


async def test_storage_failure_retry_lease_and_revoked_account(exports, organisation, sessions):
    client, app, storage = exports
    await sign_in(client, organisation["people"]["staff"])
    req = await draft(client, organisation, "10")
    item, _ = await queue(client, req)

    class Broken:
        async def put(self, *args):
            raise DomainError("SERVICE_UNAVAILABLE", "Unavailable", 503)

    claim = await claim_job(sessions, UUID(item["id"]))
    await process_claim(sessions, app.state.settings, Broken(), claim)
    assert (await client.get("/api/v1/exports/" + item["id"])).json()["status"] == "pending"
    async with sessions() as s, s.begin():
        row = await s.get(Export, UUID(item["id"]))
        row.available_at = datetime.now(UTC) - timedelta(seconds=1)
    claim = await claim_job(sessions, UUID(item["id"]))
    assert await claim_job(sessions, UUID(item["id"])) is None
    async with sessions() as s, s.begin():
        row = await s.get(Export, UUID(item["id"]))
        row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    replacement = await claim_job(sessions, UUID(item["id"]))
    await process_claim(sessions, app.state.settings, storage, claim)
    assert not storage.files
    await process_claim(sessions, app.state.settings, storage, replacement)
    assert (await client.get("/api/v1/exports/" + item["id"])).json()["status"] == "ready"
    second, _ = await queue(client, req)
    async with sessions() as s, s.begin():
        account = await s.scalar(
            select(Account).where(Account.identity_id == organisation["people"]["staff"]["id"])
        )
        account.active = False
    await generate(exports, sessions, second)
    async with sessions() as s:
        row = await s.get(Export, UUID(second["id"]))
        assert row.status == "cancelled"


@pytest.mark.parametrize(
    "outcome,state",
    [
        ("APPROVE", "APPROVED"),
        ("REJECT", "REJECTED"),
        ("DEFER", "DEFERRED"),
        ("CONDITIONAL_APPROVE", "CONDITIONALLY_APPROVED"),
    ],
)
async def test_board_outcomes_private_snapshots_and_revoked_counterpart(
    exports, organisation, sessions, outcome, state
):
    from app.organisation.models import Office
    from tests.board.test_board import act, setup

    client, _, _ = exports
    people = organisation["people"]
    case = await setup(client, organisation, outcome)
    case, _, _ = await act(client, case, people["secretary"], "board_submit")
    await sign_in(client, people["chairman"])
    case, _, _ = await act(client, case, people["chairman"], "board_confirm")
    req = case["request"]
    private, _ = await queue(client, req, include_board=True)
    await generate(exports, sessions, private)
    async with sessions() as s:
        row = await s.get(Export, UUID(private["id"]))
        assert row.status == "ready", row.last_error
        assert row.snapshot["state"] == state
        record = row.snapshot["board"][0]
        assert record["outcome"] == outcome and len(record["signatures"]) == 2
        assert record["evidence"]["filename"] == "formal-resolution.png"
        assert record["meeting_date"] == "2026-01-01"
    await sign_in(client, people["staff"])
    path = f"/api/v1/requisitions/{req['id']}/exports"
    assert not (await client.get(path)).json()["can_include_board"]
    assert (
        await client.post(
            path,
            json={
                "expected_version": req["version"],
                "idempotency_key": str(uuid4()),
                "include_board": True,
            },
        )
    ).status_code == 404
    public, _ = await queue(client, req)
    await generate(exports, sessions, public)
    async with sessions() as s:
        row = await s.get(Export, UUID(public["id"]))
        assert row.status == "ready" and row.snapshot["state"] == state
        assert row.snapshot["board"] == []
        assert row.snapshot["signatures"][1]["strokes"] == []
        assert not row.snapshot["signatures"][1]["signature_id"]
    assert (await client.get("/api/v1/exports/" + private["id"] + "/content")).status_code == 404
    await sign_in(client, people["chairman"])
    async with sessions() as s, s.begin():
        secretary = await s.scalar(
            select(Office).where(Office.identity_id == people["secretary"]["id"])
        )
        secretary.active = False
    assert (await client.get("/api/v1/exports/" + private["id"] + "/content")).status_code == 404


async def test_bank_redaction_and_frozen_revision_after_correction(exports, organisation, sessions):
    client, _, _ = exports
    people = organisation["people"]
    await sign_in(client, people["staff"])
    req = await draft(client, organisation, "500.05")
    fields = content("500.05")
    fields["vendor"].update(
        bank_name="Synthetic bank", account_name="Supplier", account_number="0012345678"
    )
    req = (
        await client.put(
            f"/api/v1/requisitions/{req['id']}/draft",
            json={"expected_version": req["version"], "content": fields},
        )
    ).json()
    req, _ = await signed(client, req, people["staff"], "submit")
    first, _ = await queue(client, req)
    await generate(exports, sessions, first)
    await sign_in(client, people["hod"])
    req, _ = await signed(client, req, people["hod"], "return", "Correction required")
    await sign_in(client, people["staff"])
    req = (
        await client.post(
            f"/api/v1/requisitions/{req['id']}/revisions",
            json={"expected_version": req["version"], "idempotency_key": str(uuid4())},
        )
    ).json()
    req = (
        await client.put(
            f"/api/v1/requisitions/{req['id']}/draft",
            json={"expected_version": req["version"], "content": content("8000000")},
        )
    ).json()
    old, _ = await queue(client, req, revision=1)
    await generate(exports, sessions, old)
    async with sessions() as s, s.begin():
        row = await s.get(Export, UUID(old["id"]))
        assert row.snapshot["total"] == "500.05"
        assert row.snapshot["content"]["vendor"]["account_number"] == "0012345678"
        assert row.snapshot["state"] == "RETURNED_FOR_REVISION"
        account = await s.scalar(
            select(Account).where(Account.identity_id == people["staff"]["id"])
        )
        account.read_only = True
    assert (await client.get("/api/v1/exports/" + old["id"] + "/content")).status_code == 404
    redacted, _ = await queue(client, req, revision=1)
    await generate(exports, sessions, redacted)
    async with sessions() as s:
        row = await s.get(Export, UUID(redacted["id"]))
        assert row.snapshot["content"]["vendor"]["account_number"] == ""
        assert row.snapshot["redacted_fields"] == ["vendor.bank_details"]


async def test_explicit_retry_preserves_capture_and_approval_after_render_failure(
    exports, organisation, sessions
):
    from app.exports.render import RenderFailure

    client, app, storage = exports
    people = organisation["people"]
    await sign_in(client, people["staff"])
    req, _ = await signed(
        client, await draft(client, organisation, "900"), people["staff"], "submit"
    )
    await sign_in(client, people["hod"])
    req, _ = await signed(client, req, people["hod"], "approve")
    item, _ = await queue(client, req)

    def fail(*args):
        raise RenderFailure("fonts_unavailable")

    claim = await claim_job(sessions, UUID(item["id"]))
    await process_claim(sessions, app.state.settings, storage, claim, fail)
    path = "/api/v1/exports/" + item["id"]
    assert (await client.get(path)).json()["status"] == "failed"
    assert (await client.get(f"/api/v1/requisitions/{req['id']}")).json()["state"] == "APPROVED"
    async with sessions() as s:
        before = (await s.get(Export, UUID(item["id"]))).snapshot
    assert (await client.post(path + "/retry")).status_code == 200
    await generate(exports, sessions, item)
    assert (await client.get(path)).json()["status"] == "ready"
    async with sessions() as s:
        after = (await s.get(Export, UUID(item["id"]))).snapshot
        assert after == before
    # Current evidence delivery verifies stored bytes, even after successful generation.
    key = next(iter(storage.files))
    storage.files[key] = b"tampered"
    assert (await client.get(path + "/content")).status_code == 503
