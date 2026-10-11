import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.audit.models import AuditEvent
from app.core.errors import DomainError
from app.evidence.models import Attachment, StagedUpload
from app.evidence.staging import cleanup
from app.identity.models import Account
from app.requisitions.models import Requisition
from tests.requisitions.test_creation import context as context
from tests.requisitions.test_creation import organisation as organisation
from tests.requisitions.test_creation import png
from tests.requisitions.test_workflow import content, sign_in, signed


def batch(org):
    return {"entity_id": org["entity_id"], "creation_key": str(uuid4())}


async def upload(client, params, **extra):
    return await client.post(
        "/api/v1/staged-attachments",
        params={
            **params,
            "upload_key": str(uuid4()),
            "filename": "quotation.png",
            **extra,
        },
        content=png(),
        headers={"content-type": "image/png"},
    )


async def test_upload_before_any_draft_claims_once_and_freezes_on_submission(
    context, organisation, sessions
):
    client, _, storage = context
    person = organisation["people"]["staff"]
    await sign_in(client, person)
    params = batch(organisation)
    key = str(uuid4())
    result = await upload(client, params, upload_key=key)
    assert result.status_code == 201, result.text
    file = result.json()
    assert (await upload(client, params, upload_key=key)).json() == file
    async with sessions() as s:
        assert not await s.scalar(
            select(Requisition).where(Requisition.creation_key == UUID(params["creation_key"]))
        )
    assert not storage.files
    assert (await client.get(f"/api/v1/staged-attachments/{file['id']}/content")).content == png()
    body = {**params, "content": content("10"), "staged_upload_ids": [file["id"]]}
    result = await client.post("/api/v1/requisitions", json=body)
    assert result.status_code == 201, result.text
    req = result.json()
    assert (await client.post("/api/v1/requisitions", json=body)).json()["id"] == req["id"]
    assert len(storage.files) == 1
    assert (await client.get(f"/api/v1/staged-attachments/{file['id']}/content")).status_code == 404
    assert (await client.get(f"/api/v1/attachments/{file['id']}/content")).content == png()
    assert (await upload(client, params)).status_code == 409
    assert (await upload(client, batch(organisation), upload_key=key)).status_code == 409
    req, _ = await signed(client, req, person, "submit")
    files = (await client.get(f"/api/v1/requisitions/{req['id']}/attachments")).json()["items"]
    assert len(files) == 1 and files[0]["frozen"]
    async with sessions() as s:
        assert not await s.get(StagedUpload, UUID(file["id"]))
        assert (
            await s.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.resource_id == UUID(file["id"]),
                    AuditEvent.action == "evidence.uploaded",
                )
            )
            == 1
        )


async def test_stage_privacy_cross_user_claim_readonly_and_remove(context, organisation, sessions):
    client, _, _ = context
    people = organisation["people"]
    await sign_in(client, people["staff"])
    params = batch(organisation)
    file = (await upload(client, params)).json()
    path = "/api/v1/staged-attachments/" + file["id"]
    await sign_in(client, people["hod"])
    assert (await client.get(path + "/content")).status_code == 404
    assert (await client.delete(path)).status_code == 404
    assert (await client.get("/api/v1/staged-attachments", params=params)).json()["items"] == []
    assert (
        await client.post(
            "/api/v1/requisitions",
            json={**params, "content": {}, "staged_upload_ids": [file["id"]]},
        )
    ).status_code == 409
    await sign_in(client, people["staff"])
    async with sessions() as s, s.begin():
        account = await s.scalar(
            select(Account).where(Account.identity_id == people["staff"]["id"])
        )
        account.read_only = True
    assert (await upload(client, params)).status_code == 403
    async with sessions() as s, s.begin():
        account = await s.scalar(
            select(Account).where(Account.identity_id == people["staff"]["id"])
        )
        account.read_only = False
    assert (await client.delete(path)).status_code == 204
    assert (await client.get(path + "/content")).status_code == 404
    assert (await client.get("/api/v1/staged-attachments", params=params)).json()["items"] == []


async def test_stage_expiry_never_silently_drops_a_selected_file(context, organisation, sessions):
    client, _, _ = context
    await sign_in(client, organisation["people"]["staff"])
    params = batch(organisation)
    file = (await upload(client, params)).json()
    async with sessions() as s, s.begin():
        staged = await s.get(StagedUpload, UUID(file["id"]))
        staged.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert (await client.get(f"/api/v1/staged-attachments/{file['id']}/content")).status_code == 404
    async with sessions() as s, s.begin():
        await cleanup(s)
    result = await client.post(
        "/api/v1/requisitions", json={**params, "content": {}, "staged_upload_ids": [file["id"]]}
    )
    assert result.status_code == 409
    async with sessions() as s:
        assert not await s.get(StagedUpload, UUID(file["id"]))
        assert not await s.scalar(
            select(Requisition).where(Requisition.creation_key == UUID(params["creation_key"]))
        )


async def test_invalid_file_limits_and_changed_retry_are_rejected(context, organisation):
    client, app, _ = context
    await sign_in(client, organisation["people"]["staff"])
    params = batch(organisation)
    bad = await client.post(
        "/api/v1/staged-attachments",
        params={**params, "upload_key": str(uuid4()), "filename": "fake.png"},
        content=b"not a png",
        headers={"content-type": "image/png"},
    )
    assert bad.status_code == 422
    app.state.settings.attachment_max_count = 1
    key = str(uuid4())
    assert (await upload(client, params, upload_key=key)).status_code == 201
    assert (await upload(client, params, upload_key=key, filename="other.png")).status_code == 409
    assert (await upload(client, params)).status_code == 422
    app.state.uploads_enabled = False
    assert (await upload(client, params)).status_code == 503


@pytest.mark.parametrize("failure", ["audit", "storage"])
async def test_claim_failure_keeps_staged_bytes_and_rolls_back_draft(
    context, organisation, sessions, monkeypatch, failure
):
    client, _, storage = context
    await sign_in(client, organisation["people"]["staff"])
    params = batch(organisation)
    file = (await upload(client, params)).json()

    async def fail(*args, **kwargs):
        if failure == "audit":
            raise SQLAlchemyError("Synthetic audit failure")
        raise DomainError("SERVICE_UNAVAILABLE", "Synthetic storage outage", 503)

    if failure == "audit":
        monkeypatch.setattr("app.evidence.staging.record_event", fail)
    else:
        monkeypatch.setattr(storage, "put", fail)
    result = await client.post(
        "/api/v1/requisitions", json={**params, "content": {}, "staged_upload_ids": [file["id"]]}
    )
    assert result.status_code == 503
    async with sessions() as s:
        assert await s.get(StagedUpload, UUID(file["id"]))
        assert not await s.get(Attachment, UUID(file["id"]))
        assert not await s.scalar(
            select(Requisition).where(Requisition.creation_key == UUID(params["creation_key"]))
        )


async def test_concurrent_create_and_upload_cannot_leave_an_unclaimed_file(context, organisation):
    client, _, _ = context
    await sign_in(client, organisation["people"]["staff"])
    params = batch(organisation)
    results = await asyncio.gather(
        client.post(
            "/api/v1/requisitions", json={**params, "content": {}, "staged_upload_ids": []}
        ),
        upload(client, params),
    )
    assert sorted(r.status_code for r in results) == [201, 409]


async def test_claim_retry_reuses_private_storage_after_audit_rollback(
    context, organisation, sessions, monkeypatch
):
    client, _, storage = context
    await sign_in(client, organisation["people"]["staff"])
    params = batch(organisation)
    file = (await upload(client, params)).json()
    body = {**params, "content": {}, "staged_upload_ids": [file["id"]]}
    from app.evidence import staging

    original = staging.record_event
    calls = []

    async def idempotent_put(key, data, media_type):
        calls.append(key)
        if key in storage.files:
            assert storage.files[key] == data
        storage.files[key] = data
        return "fixed-private-version"

    async def fail_once(*args, **kwargs):
        raise SQLAlchemyError("Synthetic audit failure")

    monkeypatch.setattr(storage, "put", idempotent_put)
    monkeypatch.setattr(staging, "record_event", fail_once)
    assert (await client.post("/api/v1/requisitions", json=body)).status_code == 503
    monkeypatch.setattr(staging, "record_event", original)
    result = await client.post("/api/v1/requisitions", json=body)
    assert result.status_code == 201, result.text
    assert len(calls) == 2 and calls[0] == calls[1]
    assert (await client.post("/api/v1/requisitions", json=body)).json()["id"] == result.json()[
        "id"
    ]
    assert len(calls) == 2
    async with sessions() as s:
        assert await s.get(Attachment, UUID(file["id"]))
        assert not await s.get(StagedUpload, UUID(file["id"]))
