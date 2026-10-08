import asyncio
import hashlib
import io
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import select

from app.audit.models import OutboxItem
from app.core.errors import DomainError
from app.evidence.models import Attachment
from app.identity.models import Account
from app.main import create_app
from app.organisation.models import Office
from app.requisitions.models import Revision, SigningChallenge
from tests.requisitions.test_workflow import (  # noqa: F401
    content,
    draft,
    sign_in,
    signed,
)
from tests.requisitions.test_workflow import organisation as organisation


class TestStorage:
    __test__ = False

    def __init__(self):
        self.files = {}

    async def put(self, key, data, media_type):
        assert key not in self.files
        self.files[key] = data
        return str(uuid4())

    async def get(self, key, digest, size):
        data = self.files.get(key, b"")
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise DomainError("SERVICE_UNAVAILABLE", "Storage unavailable.", 503)
        return data


@pytest.fixture
async def context(settings):
    app = create_app(settings)
    storage = TestStorage()
    app.state.evidence_storage = storage
    app.state.uploads_enabled = True
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app),
            base_url="http://test",
            headers={"origin": "http://localhost:5173"},
        ) as client:
            yield client, app, storage


def png():
    out = io.BytesIO()
    Image.new("RGB", (2, 2)).save(out, format="PNG")
    return out.getvalue()


async def upload(client, req, data=None, **params):
    return await client.post(
        f"/api/v1/requisitions/{req['id']}/attachments",
        params={
            "filename": "quotation.png",
            "expected_version": req["version"],
            "upload_key": str(uuid4()),
            **params,
        },
        content=data if data is not None else png(),
        headers={"content-type": "image/png"},
    )


async def test_incomplete_draft_idempotency_search_and_conflict(context, organisation):
    client, _, _ = context
    await sign_in(client, organisation["people"]["staff"])
    body = {"entity_id": organisation["entity_id"], "creation_key": str(uuid4()), "content": {}}
    first = await client.post("/api/v1/requisitions", json=body)
    assert first.status_code == 201
    req = first.json()
    assert req["total"] == "0.00" and req["submission_blocker"]
    assert (await client.post("/api/v1/requisitions", json=body)).json()["id"] == req["id"]
    body["content"] = content("71640")
    assert (await client.post("/api/v1/requisitions", json=body)).status_code == 409
    update = {"expected_version": req["version"], "content": content("71640")}
    results = await asyncio.gather(
        *[client.put(f"/api/v1/requisitions/{req['id']}/draft", json=update) for _ in range(2)]
    )
    assert sorted(r.status_code for r in results) == [200, 409]
    page = (
        await client.get(
            "/api/v1/requisitions", params={"search": req["reference"], "state": "DRAFT"}
        )
    ).json()
    assert page["total"] == 1 and page["items"][0]["total"] == "71640.00"
    assert (await client.get("/api/v1/requisitions?search=%25")).json()["total"] == 0
    await sign_in(client, organisation["people"]["other_hod"])
    assert (await client.get("/api/v1/requisitions", params={"search": req["reference"]})).json()[
        "total"
    ] == 0
    assert (await client.get("/api/v1/requisitions/" + req["id"])).status_code == 404


async def test_documents_signed_manifest_private_access_and_outbox(context, organisation, sessions):
    client, _, _ = context
    people = organisation["people"]
    await sign_in(client, people["staff"])
    req = await draft(client, organisation, "71640")
    key = str(uuid4())
    response = await upload(client, req, upload_key=key)
    assert response.status_code == 201, response.text
    file = response.json()
    assert file["malware_scan"] == "not_performed"
    assert (await upload(client, req, upload_key=key)).json()["id"] == file["id"]
    download = await client.get("/api/v1/attachments/" + file["id"] + "/content")
    assert download.content == png() and download.headers["cache-control"] == "no-store"
    req = (await client.get("/api/v1/requisitions/" + req["id"])).json()
    submitted, command = await signed(client, req, people["staff"], "submit")
    assert submitted["state"] == "PENDING_AUTHORITY"
    assert (
        await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=command)
    ).json() == submitted
    assert (
        await client.delete(
            "/api/v1/attachments/" + file["id"], params={"expected_version": submitted["version"]}
        )
    ).status_code == 403
    async with sessions() as s:
        revision = await s.scalar(
            select(Revision).where(Revision.requisition_id == UUID(req["id"]))
        )
        assert revision.context["attachments"][0]["digest"] == file["digest"]
        assert revision.signature["declaration_version"] == "originator-v1"
        assert revision.signature["authenticated_at"]
        assert (await s.get(Attachment, UUID(file["id"]))).frozen
        assert await s.scalar(
            select(OutboxItem.id).where(OutboxItem.destination == "requisition_notification")
        )
    await sign_in(client, people["other_hod"])
    assert (await client.get("/api/v1/attachments/" + file["id"] + "/content")).status_code == 404
    await sign_in(client, people["hod"])
    assert (await client.get("/api/v1/attachments/" + file["id"] + "/content")).content == png()
    assert (
        await client.post(
            f"/api/v1/requisitions/{req['id']}/signing-challenges",
            json={"expected_version": submitted["version"], "action": "approve"},
        )
    ).status_code == 403


async def test_document_validation_unavailable_storage_and_stale_challenge(context, organisation):
    client, app, storage = context
    person = organisation["people"]["staff"]
    await sign_in(client, person)
    req = await draft(client, organisation, "1")
    assert (await upload(client, req, data=b"not an image")).status_code == 422
    assert (await upload(client, req, filename="../bad.png")).status_code == 422
    app.state.settings.attachment_max_bytes = 1024
    assert (await upload(client, req, data=b"x" * 1025)).status_code == 422
    intent = {"expected_version": req["version"], "action": "submit"}
    challenge = (
        await client.post(f"/api/v1/requisitions/{req['id']}/signing-challenges", json=intent)
    ).json()
    response = await upload(client, req)
    assert response.status_code == 201
    command = {
        **intent,
        "challenge_id": challenge["id"],
        "idempotency_key": str(uuid4()),
        "signer_name": person["name"],
        "consent": True,
        "strokes": [[{"x": 0, "y": 0}] * 3],
    }
    assert (
        await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=command)
    ).status_code == 409
    req = (await client.get("/api/v1/requisitions/" + req["id"])).json()
    storage.files.clear()
    intent["expected_version"] = req["version"]
    challenge = (
        await client.post(f"/api/v1/requisitions/{req['id']}/signing-challenges", json=intent)
    ).json()
    command.update(expected_version=req["version"], challenge_id=challenge["id"])
    assert (
        await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=command)
    ).status_code == 503
    assert (await client.get("/api/v1/requisitions/" + req["id"])).json()["state"] == "DRAFT"
    assert (
        await client.delete(
            "/api/v1/attachments/" + response.json()["id"],
            params={"expected_version": req["version"]},
        )
    ).status_code == 204


async def test_route_assignment_change_invalidates_signature(context, organisation, sessions):
    client, _, _ = context
    person = organisation["people"]["staff"]
    await sign_in(client, person)
    req = await draft(client, organisation, "5000000.01")
    assert req["required_authority"] == "chief_of_staff" and req["submission_blocker"] is None
    async with sessions() as s, s.begin():
        office = await s.scalar(
            select(Office).where(
                Office.identity_id == organisation["people"]["chief_of_staff"]["id"]
            )
        )
        office.active = False
    view = (await client.get("/api/v1/requisitions/" + req["id"])).json()
    assert "unique active" in view["submission_blocker"]
    assert (
        await client.post(
            f"/api/v1/requisitions/{req['id']}/signing-challenges",
            json={"expected_version": req["version"], "action": "submit"},
        )
    ).status_code == 409


async def test_expired_signature_and_bank_redaction_on_replay(context, organisation, sessions):
    client, _, _ = context
    person = organisation["people"]["staff"]
    await sign_in(client, person)
    req = await draft(client, organisation, "10")
    full = content("10")
    full["vendor"].update(
        bank_name="Synthetic Bank", account_name="Synthetic supplier", account_number="001234"
    )
    req = (
        await client.put(
            f"/api/v1/requisitions/{req['id']}/draft",
            json={"expected_version": req["version"], "content": full},
        )
    ).json()
    intent = {"expected_version": req["version"], "action": "submit"}
    challenge = (
        await client.post(f"/api/v1/requisitions/{req['id']}/signing-challenges", json=intent)
    ).json()
    async with sessions() as s, s.begin():
        (await s.get(SigningChallenge, UUID(challenge["id"]))).expires_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
    command = {
        **intent,
        "challenge_id": challenge["id"],
        "idempotency_key": str(uuid4()),
        "signer_name": person["name"],
        "consent": True,
        "strokes": [[{"x": 0, "y": 0}] * 3],
    }
    assert (await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=command)).json()[
        "code"
    ] == "SIGNATURE_INVALID"
    _, command = await signed(client, req, person, "submit")
    async with sessions() as s, s.begin():
        account = await s.scalar(select(Account).where(Account.identity_id == person["id"]))
        account.read_only = True
    replay = await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=command)
    assert replay.status_code == 200
    assert replay.json()["content"]["vendor"]["account_number"] == ""
    assert replay.json()["redacted_fields"] == ["vendor.bank_details"]


async def test_vendor_selection_is_scoped_versioned_and_frozen(context, organisation, sessions):
    client, _, _ = context
    person = organisation["people"]["staff"]
    await sign_in(client, person)
    data = {
        "name": "Synthetic selected supplier",
        "bank": {"bank_name": "Bank", "account_number": "000123", "account_name": "Supplier"},
    }
    vendor = (
        await client.post(
            "/api/v1/vendors", json={"entity_id": organisation["entity_id"], "data": data}
        )
    ).json()
    body = {
        "entity_id": organisation["entity_id"],
        "creation_key": str(uuid4()),
        "content": content("10"),
        "vendor_selection": {"id": vendor["id"], "expected_version": vendor["version"]},
    }
    response = await client.post("/api/v1/requisitions", json=body)
    assert response.status_code == 201, response.text
    req = response.json()
    assert req["content"]["vendor"]["account_number"] == "000123"
    req, _ = await signed(client, req, person, "submit")
    data["name"] = "Renamed supplier"
    assert (
        await client.patch(
            "/api/v1/vendors/" + vendor["id"], json={"expected_version": 1, "data": data}
        )
    ).status_code == 200
    assert (await client.get("/api/v1/requisitions/" + req["id"])).json()["content"]["vendor"][
        "name"
    ] == "Synthetic selected supplier"
    body["creation_key"] = str(uuid4())
    assert (await client.post("/api/v1/requisitions", json=body)).status_code == 409
    async with sessions() as s:
        revision = await s.scalar(
            select(Revision).where(Revision.requisition_id == UUID(req["id"]))
        )
        assert revision.context["context"]["vendor_version_id"] == vendor["version_id"]


async def test_submission_audit_failure_rolls_back_signature_and_frozen_files(
    context, organisation, sessions, monkeypatch
):
    from sqlalchemy.exc import SQLAlchemyError

    from app.requisitions.models import Requisition

    client, _, _ = context
    person = organisation["people"]["staff"]
    await sign_in(client, person)
    req = await draft(client, organisation, "10")
    file = (await upload(client, req)).json()
    req = (await client.get("/api/v1/requisitions/" + req["id"])).json()
    intent = {"expected_version": req["version"], "action": "submit"}
    challenge = (
        await client.post(f"/api/v1/requisitions/{req['id']}/signing-challenges", json=intent)
    ).json()
    command = {
        **intent,
        "challenge_id": challenge["id"],
        "idempotency_key": str(uuid4()),
        "signer_name": person["name"],
        "consent": True,
        "strokes": [[{"x": 0, "y": 0}] * 3],
    }

    async def fail(*args, **kwargs):
        raise SQLAlchemyError("Synthetic audit outage")

    monkeypatch.setattr("app.requisitions.router.record_event", fail)
    assert (
        await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=command)
    ).status_code == 503
    async with sessions() as s:
        assert not (await s.get(SigningChallenge, UUID(challenge["id"]))).consumed
        assert not (await s.get(Attachment, UUID(file["id"]))).frozen
        assert (await s.get(Requisition, UUID(req["id"]))).state == "DRAFT"
        assert (
            await s.scalar(select(Revision.id).where(Revision.requisition_id == UUID(req["id"])))
            is None
        )


async def test_concurrent_submission_records_one_revision_and_rejects_forged_content(
    context, organisation, sessions
):
    from sqlalchemy import func

    client, _, _ = context
    person = organisation["people"]["staff"]
    await sign_in(client, person)
    bad = {
        "entity_id": organisation["entity_id"],
        "creation_key": str(uuid4()),
        "content": content("10"),
        "requester_id": str(person["id"]),
    }
    assert (await client.post("/api/v1/requisitions", json=bad)).status_code == 422
    req = await draft(client, organisation, "10")
    intent = {"expected_version": req["version"], "action": "submit"}
    challenge = (
        await client.post(f"/api/v1/requisitions/{req['id']}/signing-challenges", json=intent)
    ).json()
    command = {
        **intent,
        "challenge_id": challenge["id"],
        "idempotency_key": str(uuid4()),
        "signer_name": person["name"],
        "consent": True,
        "strokes": [[{"x": 0, "y": 0}] * 3],
    }
    responses = await asyncio.gather(
        *[client.post(f"/api/v1/requisitions/{req['id']}/actions", json=command) for _ in range(2)]
    )
    assert [r.status_code for r in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    async with sessions() as s:
        assert (
            await s.scalar(
                select(func.count())
                .select_from(Revision)
                .where(Revision.requisition_id == UUID(req["id"]))
            )
            == 1
        )
    command["idempotency_key"] = str(uuid4())
    assert (
        await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=command)
    ).status_code == 403


async def test_vendor_restricted_bank_is_never_copied(context, organisation):
    client, _, _ = context
    await sign_in(client, organisation["people"]["staff"])
    vendor = (
        await client.post(
            "/api/v1/vendors",
            json={
                "entity_id": organisation["entity_id"],
                "data": {
                    "name": "Synthetic private vendor",
                    "bank": {
                        "bank_name": "Bank",
                        "account_number": "007700",
                        "account_name": "Private",
                    },
                },
            },
        )
    ).json()
    await sign_in(client, organisation["people"]["hod"])
    response = await client.post(
        "/api/v1/requisitions",
        json={
            "entity_id": organisation["entity_id"],
            "creation_key": str(uuid4()),
            "content": content("10"),
            "vendor_selection": {"id": vendor["id"], "expected_version": 1},
        },
    )
    assert response.status_code == 201
    assert response.json()["content"]["vendor"]["account_number"] == ""
    assert response.json()["redacted_fields"] == ["vendor.bank_details"]


def test_malformed_png_and_pdf_validation():
    import base64

    from pypdf import PdfWriter

    from app.evidence.validation import validate

    bad = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aG7sAAAAASUVORK5CYII="
    )
    with pytest.raises(DomainError):
        validate(bad, "broken.png", "image/png", 1024)
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(output)
    assert validate(output.getvalue(), "quote.pdf", "application/pdf", 4096) == (
        "quote.pdf",
        "application/pdf",
    )
    with pytest.raises(DomainError):
        validate(b"%PDF-1.7\nbroken\n%%EOF", "broken.pdf", "application/pdf", 4096)


async def test_complete_draft_roundtrip_and_immutable_attachment_metadata(
    context, organisation, sessions
):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    client, _, _ = context
    person = organisation["people"]["staff"]
    await sign_in(client, person)
    full = content("1")
    full.update(
        start_date="2026-10-09",
        completion_date="2026-10-10",
        payment_terms="On delivery",
        warranty="Not applicable",
    )
    full["vendor"].update(
        contact_person="Synthetic contact",
        phone="000",
        email="synthetic@example.com",
        address="Synthetic address",
        registration_id="SYNTHETIC-RC",
        bank_name="Synthetic bank",
        account_name="Supplier",
        account_number="00123",
    )
    full["lines"] = [
        {"description": f"Item {i}", "quantity": "1", "unit_price": str(price)}
        for i, price in enumerate([2890, 3400, 7450, 1400, 27500, 29000])
    ]
    response = await client.post(
        "/api/v1/requisitions",
        json={
            "entity_id": organisation["entity_id"],
            "creation_key": str(uuid4()),
            "content": full,
        },
    )
    assert response.status_code == 201
    req = response.json()
    loaded = (await client.get("/api/v1/requisitions/" + req["id"])).json()
    assert loaded["total"] == "71640.00"
    for key, value in full.items():
        assert loaded["content"][key] == value
    file = (await upload(client, loaded)).json()
    loaded = (await client.get("/api/v1/requisitions/" + req["id"])).json()
    submitted, _ = await signed(client, loaded, person, "submit")
    assert (
        await client.put(
            f"/api/v1/requisitions/{req['id']}/draft",
            json={"expected_version": submitted["version"], "content": full},
        )
    ).status_code == 403
    with pytest.raises(DBAPIError):
        async with sessions() as s, s.begin():
            await s.execute(
                text("UPDATE custodian.attachments SET digest=:digest WHERE id=:id"),
                {"digest": "0" * 64, "id": UUID(file["id"])},
            )


async def test_signing_expiry_during_storage_read_rolls_back(context, organisation, monkeypatch):
    client, _, storage = context
    person = organisation["people"]["staff"]
    await sign_in(client, person)
    req = await draft(client, organisation, "10")
    assert (await upload(client, req)).status_code == 201
    req = (await client.get("/api/v1/requisitions/" + req["id"])).json()
    intent = {"expected_version": req["version"], "action": "submit"}
    challenge = (
        await client.post(f"/api/v1/requisitions/{req['id']}/signing-challenges", json=intent)
    ).json()

    class Clock:
        advanced = False

        @classmethod
        def now(cls, tz):
            return datetime.now(tz) + (timedelta(minutes=20) if cls.advanced else timedelta())

    original = storage.get

    async def slow(*args):
        result = await original(*args)
        Clock.advanced = True
        return result

    monkeypatch.setattr("app.requisitions.router.datetime", Clock)
    monkeypatch.setattr(storage, "get", slow)
    command = {
        **intent,
        "challenge_id": challenge["id"],
        "idempotency_key": str(uuid4()),
        "signer_name": person["name"],
        "consent": True,
        "strokes": [[{"x": 0, "y": 0}] * 3],
    }
    response = await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=command)
    assert response.status_code == 409 and response.json()["code"] == "SIGNATURE_INVALID"
    assert (await client.get("/api/v1/requisitions/" + req["id"])).json()["state"] == "DRAFT"


async def test_draft_survives_new_application_and_another_actor_cannot_use_its_challenge(
    context, organisation, settings
):
    client, _, _ = context
    staff, hod = organisation["people"]["staff"], organisation["people"]["hod"]
    await sign_in(client, staff)
    req = await draft(client, organisation, "10")
    intent = {"expected_version": req["version"], "action": "submit"}
    challenge = (
        await client.post(f"/api/v1/requisitions/{req['id']}/signing-challenges", json=intent)
    ).json()
    # A new application and connection pool have no access to the original process state.
    restarted = create_app(settings)
    async with restarted.router.lifespan_context(restarted):
        async with AsyncClient(
            transport=ASGITransport(restarted),
            base_url="http://test",
            headers={"origin": "http://localhost:5173"},
        ) as other:
            await sign_in(other, staff)
            restored = (await other.get("/api/v1/requisitions/" + req["id"])).json()
            assert restored["content"] == req["content"] and restored["version"] == req["version"]
            await sign_in(other, hod)
            own = await draft(other, organisation, "10")
            command = {
                "expected_version": own["version"],
                "action": "submit",
                "challenge_id": challenge["id"],
                "idempotency_key": str(uuid4()),
                "signer_name": hod["name"],
                "consent": True,
                "strokes": [[{"x": 0, "y": 0}] * 3],
            }
            response = await other.post(f"/api/v1/requisitions/{own['id']}/actions", json=command)
            assert response.status_code == 409 and response.json()["code"] == "SIGNATURE_INVALID"
            assert (await other.get("/api/v1/requisitions/" + own["id"])).json()["state"] == "DRAFT"
