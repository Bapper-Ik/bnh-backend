from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.database import Identity
from app.identity.models import Account
from app.identity.service import hasher
from app.organisation.models import Department, Entity, Membership
from app.requisitions.models import Requisition, Revision
from app.vendor_app import create_app
from app.vendors.models import BeneficiaryVersion, VendorVersion

PASSWORD = "Synthetic-vendor-password-2026"


@pytest.fixture
async def vendor_context(settings, sessions):
    people = []
    async with sessions() as s, s.begin():
        entities = [Entity(name=f"Synthetic vendor company {uuid4()}") for _ in range(2)]
        s.add_all(entities)
        await s.flush()
        departments = [Department(entity_id=e.id, name="Operations") for e in entities]
        s.add_all(departments)
        await s.flush()
        for index in range(3):
            identity = Identity(display_name=f"Synthetic vendor staff {index}")
            s.add(identity)
            await s.flush()
            account = Account(
                identity_id=identity.id,
                email=f"{uuid4()}@example.com",
                password_hash=hasher.hash(PASSWORD),
                permissions=[],
            )
            s.add(account)
            company = 1 if index == 2 else 0
            s.add(
                Membership(
                    identity_id=identity.id,
                    entity_id=entities[company].id,
                    department_id=departments[company].id,
                )
            )
            people.append(account)
        await s.flush()
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app),
            base_url="http://test",
            headers={"origin": "http://localhost:5173"},
        ) as client:
            context = {
                "client": client,
                "app": app,
                "people": people,
                "entity": entities[0].id,
                "department": departments[0].id,
            }
            await login(context, 0)
            yield context


async def login(context, index):
    response = await context["client"].post(
        "/api/v1/auth/login", json={"email": context["people"][index].email, "password": PASSWORD}
    )
    assert response.status_code == 200
    context["client"].headers["x-csrf-token"] = context["client"].cookies.get("custodian_csrf")


def data(bank=True):
    return {
        "name": "Synthetic supplier",
        "phones": ["+234 000 000 0000", "+234 000 000 0001"],
        "email": "synthetic@example.com",
        "bank": {
            "bank_name": "Synthetic bank",
            "account_number": "0000000001",
            "account_name": "Synthetic beneficiary",
        }
        if bank
        else None,
    }


async def create(context, content=None):
    response = await context["client"].post(
        "/api/v1/vendors", json={"entity_id": str(context["entity"]), "data": content or data()}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_lookup_hides_bank_details_and_cross_entity_vendor_access(vendor_context):
    record = await create(vendor_context)
    listing = await vendor_context["client"].get(
        f"/api/v1/vendors?entity_id={vendor_context['entity']}"
    )
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert "0000000001" not in listing.text
    assert "bank_name" not in listing.text
    await login(vendor_context, 1)
    detail = await vendor_context["client"].get(f"/api/v1/vendors/{record['id']}")
    assert detail.status_code == 200
    assert detail.json()["can_update"] is False
    assert detail.json()["bank_details_state"] == "restricted"
    assert detail.json()["data"]["bank"] is None
    assert detail.json()["beneficiary_version_id"] is None
    assert (
        await vendor_context["client"].patch(
            f"/api/v1/vendors/{record['id']}", json={"expected_version": 1, "data": data()}
        )
    ).status_code == 403
    await login(vendor_context, 2)
    assert (
        await vendor_context["client"].get(f"/api/v1/vendors/{record['id']}")
    ).status_code == 404
    assert (
        await vendor_context["client"].get(f"/api/v1/vendors?entity_id={vendor_context['entity']}")
    ).status_code == 403


async def test_bank_details_are_all_or_none_and_preserve_zeroes(vendor_context):
    response = await vendor_context["client"].post(
        "/api/v1/vendors",
        json={
            "entity_id": str(vendor_context["entity"]),
            "data": {**data(), "bank": {"bank_name": "Synthetic bank"}},
        },
    )
    assert response.status_code == 422
    record = await create(vendor_context)
    loaded = await vendor_context["client"].get(f"/api/v1/vendors/{record['id']}")
    assert loaded.json()["can_update"] is True
    assert loaded.json()["data"]["bank"]["account_number"] == "0000000001"
    assert loaded.json()["data"]["phones"] == data()["phones"]
    absent = await create(vendor_context, data(False))
    assert absent["bank_details_state"] == "unknown"
    assert absent["beneficiary_version_id"] is None
    assert absent["verification"] == "not_verified"


async def test_duplicate_names_are_distinct_and_search_is_paginated(vendor_context):
    first, second = await create(vendor_context), await create(vendor_context)
    assert first["id"] != second["id"]
    response = await vendor_context["client"].get(
        f"/api/v1/vendors?entity_id={vendor_context['entity']}&search=Synthetic&limit=1"
    )
    assert response.json()["total"] == 2
    assert len(response.json()["items"]) == 1
    # SQL wildcard characters are literal search text, not a scope bypass.
    response = await vendor_context["client"].get(
        f"/api/v1/vendors?entity_id={vendor_context['entity']}&search=%25"
    )
    assert response.json()["total"] == 0


async def test_vendor_updates_do_not_rewrite_submitted_snapshot(vendor_context, sessions):
    saved = await create(vendor_context)
    async with sessions() as s, s.begin():
        request = Requisition(
            id=uuid4(),
            reference=f"SYNTHETIC-{uuid4()}",
            requester_id=vendor_context["people"][0].identity_id,
            entity_id=vendor_context["entity"],
            department_id=vendor_context["department"],
            creation_key=uuid4(),
            creation_digest="synthetic",
            state="PENDING_AUTHORITY",
            version=2,
            content={"vendor": saved["data"], "vendor_version_id": saved["version_id"]},
            total=Decimal("1"),
            revision_number=1,
        )
        s.add(request)
        await s.flush()
        revision = Revision(
            id=uuid4(),
            requisition_id=request.id,
            number=1,
            content=request.content,
            total=request.total,
            requester_name="Synthetic staff",
            department_name="Operations",
            entity_name="Synthetic company",
            authority="hod",
            approver_id=None,
            policy_version="bnh-doa-v1",
            routing_explanation="Synthetic test",
            content_digest="a" * 64,
            signature={},
        )
        s.add(revision)
        await s.flush()
        revision_id = revision.id
    changed = {
        **data(),
        "name": "Changed supplier",
        "bank": {**data()["bank"], "account_number": "0000000002"},
    }
    response = await vendor_context["client"].patch(
        f"/api/v1/vendors/{saved['id']}", json={"expected_version": 1, "data": changed}
    )
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert response.json()["beneficiary_version_id"] != saved["beneficiary_version_id"]
    history = await vendor_context["client"].get(f"/api/v1/vendors/{saved['id']}/versions/1")
    assert history.json()["can_update"] is False
    assert history.json()["data"] == saved["data"]
    async with sessions() as s:
        snapshot = await s.get(Revision, revision_id)
        assert snapshot.content["vendor"] == saved["data"]
        assert snapshot.content["vendor_version_id"] == saved["version_id"]
        assert (
            await s.get(BeneficiaryVersion, UUID(saved["beneficiary_version_id"]))
        ).account_number == "0000000001"


async def test_optimistic_vendor_updates_reject_stale_writes(vendor_context):
    saved = await create(vendor_context)
    payload = {"expected_version": 1, "data": {**data(), "name": "New supplier name"}}
    response = await vendor_context["client"].patch(f"/api/v1/vendors/{saved['id']}", json=payload)
    assert response.status_code == 200
    response = await vendor_context["client"].patch(f"/api/v1/vendors/{saved['id']}", json=payload)
    assert response.status_code == 409
    assert response.json()["code"] == "REVISION_CONFLICT"


@pytest.mark.parametrize("table", ["vendor_versions", "beneficiary_versions"])
@pytest.mark.parametrize("action", ["UPDATE", "DELETE", "TRUNCATE"])
async def test_runtime_cannot_rewrite_vendor_history(vendor_context, sessions, table, action):
    await create(vendor_context)
    sql = (
        f"UPDATE custodian.{table} SET id=id"
        if action == "UPDATE"
        else f"DELETE FROM custodian.{table}"
        if action == "DELETE"
        else f"TRUNCATE custodian.{table} CASCADE"
    )
    with pytest.raises(DBAPIError):
        async with sessions() as s, s.begin():
            await s.execute(text(sql))


async def test_readonly_account_cannot_change_its_existing_vendor(vendor_context, sessions):
    saved = await create(vendor_context)
    async with sessions() as s, s.begin():
        (await s.get(Account, vendor_context["people"][0].id)).read_only = True
    detail = await vendor_context["client"].get(f"/api/v1/vendors/{saved['id']}")
    assert detail.json()["can_update"] is False
    assert detail.json()["bank_details_state"] == "restricted"
    assert (
        await vendor_context["client"].patch(
            f"/api/v1/vendors/{saved['id']}", json={"expected_version": 1, "data": data()}
        )
    ).status_code == 403


async def test_concurrent_authorised_updates_commit_one_version(vendor_context, sessions):
    import asyncio

    from app.audit.models import AuditEvent

    saved = await create(vendor_context)
    manager = vendor_context["people"][1]
    async with sessions() as s, s.begin():
        (await s.get(Account, manager.id)).permissions = ["vendor:update", "vendor:read_sensitive"]
    async with AsyncClient(
        transport=ASGITransport(vendor_context["app"]),
        base_url="http://test",
        headers={"origin": "http://localhost:5173"},
    ) as second:
        assert (
            await second.post(
                "/api/v1/auth/login", json={"email": manager.email, "password": PASSWORD}
            )
        ).status_code == 200
        second.headers["x-csrf-token"] = second.cookies.get("custodian_csrf")
        detail = await second.get(f"/api/v1/vendors/{saved['id']}")
        assert detail.json()["data"]["bank"]["account_number"] == "0000000001"
        payload = {"expected_version": 1, "data": {**data(), "name": "Concurrent supplier update"}}
        results = await asyncio.gather(
            vendor_context["client"].patch(f"/api/v1/vendors/{saved['id']}", json=payload),
            second.patch(f"/api/v1/vendors/{saved['id']}", json=payload),
        )
        assert sorted(response.status_code for response in results) == [200, 409]
        rejected = next(response for response in results if response.status_code == 409)
    async with sessions() as s:
        versions = (
            await s.scalars(
                select(VendorVersion).where(VendorVersion.vendor_id == UUID(saved["id"]))
            )
        ).all()
        assert len(versions) == 2
        event = await s.scalar(
            select(AuditEvent).where(
                AuditEvent.correlation_id == UUID(rejected.headers["x-request-id"]),
                AuditEvent.action == "vendor.update_failed",
            )
        )
        assert event.details["outcome"] == "denied"
        assert "0000000001" not in str(event.details)
