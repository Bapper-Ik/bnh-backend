from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.access.roles import SYSTEM_ADMIN_PERMISSIONS
from app.identity.models import Account
from app.organisation.models import Department, Membership, Office
from tests.requisitions.test_creation import context as context
from tests.requisitions.test_workflow import content, sign_in
from tests.requisitions.test_workflow import organisation as organisation
from tests.vendors.test_vendors import create, data, login
from tests.vendors.test_vendors import vendor_context as vendor_context


async def appoint(sessions, ctx, role="hod"):
    async with sessions() as s, s.begin():
        office = Office(
            identity_id=ctx["people"][1].identity_id,
            entity_id=ctx["entity"],
            department_id=ctx["department"] if role == "hod" else None,
            role=role,
            valid_from=datetime.now(UTC) - timedelta(days=1),
            authorisation_reference="Synthetic bank-access test",
        )
        s.add(office)
        await s.flush()
        return office.id


@pytest.mark.parametrize("role", ["hod", "chief_of_staff", "md", "secretary", "chairman"])
async def test_officers_see_current_and_historical_bank_details_without_vendor_write(
    vendor_context, sessions, role
):
    ctx = vendor_context
    saved = await create(ctx)
    await appoint(sessions, ctx, role)
    await login(ctx, 1)
    c = ctx["client"]
    listing = await c.get(f"/api/v1/vendors?entity_id={ctx['entity']}")
    assert listing.json()["items"][0]["bank_details_state"] == "supplied"
    assert "0000000001" not in listing.text  # Search summaries never contain account numbers.
    for suffix in ("", "/versions/1"):
        response = await c.get(f"/api/v1/vendors/{saved['id']}" + suffix)
        assert response.status_code == 200
        assert response.json()["data"]["bank"]["account_number"] == "0000000001"
        assert response.json()["bank_details_state"] == "supplied"
        assert not response.json()["can_update"]
    assert (
        await c.patch(
            f"/api/v1/vendors/{saved['id']}", json={"expected_version": 1, "data": data()}
        )
    ).status_code == 403


@pytest.mark.parametrize(
    "loss", ["inactive", "expired", "future", "readonly", "membership", "department"]
)
async def test_bank_access_is_rechecked_when_office_or_membership_changes(
    vendor_context, sessions, loss
):
    ctx = vendor_context
    saved = await create(ctx)
    office_id = await appoint(sessions, ctx)
    await login(ctx, 1)
    c = ctx["client"]
    path = f"/api/v1/vendors/{saved['id']}"
    assert (await c.get(path)).json()["data"]["bank"] is not None
    async with sessions() as s, s.begin():
        office = await s.get(Office, office_id)
        if loss == "inactive":
            office.active = False
        elif loss == "expired":
            office.valid_until = datetime.now(UTC) - timedelta(hours=1)
        elif loss == "future":
            office.valid_from = datetime.now(UTC) + timedelta(days=1)
        elif loss == "readonly":
            (await s.get(Account, ctx["people"][1].id)).read_only = True
        elif loss == "membership":
            member = await s.scalar(
                select(Membership).where(
                    Membership.identity_id == ctx["people"][1].identity_id,
                    Membership.entity_id == ctx["entity"],
                )
            )
            member.active = False
        else:
            (await s.get(Department, ctx["department"])).active = False
    for suffix in ("", "/versions/1"):
        response = await c.get(path + suffix)
        assert "0000000001" not in response.text
        if loss in {"membership", "department"}:
            assert response.status_code == 404
        else:
            assert response.status_code == 200
            assert response.json()["data"]["bank"] is None
            assert response.json()["bank_details_state"] == "restricted"


async def test_office_in_other_company_does_not_unmask_member_company_vendor(
    vendor_context, sessions
):
    ctx = vendor_context
    saved = await create(ctx)
    async with sessions() as s, s.begin():
        other = await s.scalar(
            select(Membership).where(Membership.identity_id == ctx["people"][2].identity_id)
        )
        s.add(
            Membership(
                identity_id=ctx["people"][1].identity_id,
                entity_id=other.entity_id,
                department_id=other.department_id,
            )
        )
        s.add(
            Office(
                identity_id=ctx["people"][1].identity_id,
                entity_id=other.entity_id,
                role="md",
                valid_from=datetime.now(UTC) - timedelta(days=1),
                authorisation_reference="Synthetic other-company appointment",
            )
        )
    await login(ctx, 1)
    response = await ctx["client"].get(f"/api/v1/vendors/{saved['id']}")
    assert response.status_code == 200 and response.json()["data"]["bank"] is None


async def test_only_full_administrators_receive_automatic_bank_access(vendor_context, sessions):
    ctx = vendor_context
    saved = await create(ctx)
    await login(ctx, 1)
    path = f"/api/v1/vendors/{saved['id']}"
    async with sessions() as s, s.begin():
        (await s.get(Account, ctx["people"][1].id)).permissions = sorted(SYSTEM_ADMIN_PERMISSIONS)
    assert (await ctx["client"].get(path)).json()["data"]["bank"]["account_number"] == "0000000001"
    async with sessions() as s, s.begin():
        (await s.get(Account, ctx["people"][1].id)).permissions = [
            "staff:manage",
            "organisation:manage",
        ]
    assert (await ctx["client"].get(path)).json()["data"]["bank"] is None
    await login(ctx, 0)
    own = (await ctx["client"].get(path)).json()
    assert own["data"]["bank"]["account_number"] == "0000000001" and own["can_update"]
    listing = await ctx["client"].get(f"/api/v1/vendors?entity_id={ctx['entity']}")
    assert listing.json()["items"][0]["bank_details_state"] == "supplied"


async def test_officer_selection_copies_authorised_bank_details_into_new_draft(
    context, organisation
):
    c = context[0]
    await sign_in(c, organisation["people"]["staff"])
    saved = await c.post(
        "/api/v1/vendors", json={"entity_id": organisation["entity_id"], "data": data()}
    )
    assert saved.status_code == 201
    from uuid import uuid4

    await sign_in(c, organisation["people"]["hod"])
    request = await c.post(
        "/api/v1/requisitions",
        json={
            "entity_id": organisation["entity_id"],
            "creation_key": str(uuid4()),
            "content": content("248000"),
            "vendor_selection": {"id": saved.json()["id"], "expected_version": 1},
        },
    )
    assert request.status_code == 201, request.text
    assert request.json()["content"]["vendor"]["account_number"] == "0000000001"
    assert request.json()["redacted_fields"] == []
