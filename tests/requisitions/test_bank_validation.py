from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.requisitions.models import Requisition
from app.requisitions.schemas import Content
from app.transfers.schemas import DebitAccountUpdate
from app.vendors.schemas import CreateVendor, UpdateVendor
from tests.requisitions.test_workflow import client as client
from tests.requisitions.test_workflow import content, draft, sign_in
from tests.requisitions.test_workflow import organisation as organisation
from tests.transfers.test_transfers import DEBIT

BANK = {"bank_name": "Synthetic bank", "account_name": "Synthetic beneficiary"}


@pytest.mark.parametrize(
    "number",
    ["123456789", "12345678901", "00123abc45", "12345.6789", "１２３４５６７８９０", "1e00000009"],
)
async def test_invalid_bank_numbers_rejected_for_creation_and_updates(client, organisation, number):
    await sign_in(client, organisation["people"]["staff"])
    req = await draft(client, organisation, "10")
    body = content("10")
    body["vendor"].update(**BANK, account_number=number)
    created = await client.post(
        "/api/v1/requisitions",
        json={
            "entity_id": organisation["entity_id"],
            "creation_key": str(uuid4()),
            "content": body,
        },
    )
    assert created.status_code == 422 and "exactly 10 digits" in created.text
    updated = await client.put(
        f"/api/v1/requisitions/{req['id']}/draft",
        json={"expected_version": req["version"], "content": body},
    )
    assert updated.status_code == 422
    assert (await client.get(f"/api/v1/requisitions/{req['id']}")).json()["version"] == req[
        "version"
    ]
    for schema, command in [
        (
            CreateVendor,
            {
                "entity_id": organisation["entity_id"],
                "data": {"name": "Synthetic vendor", "bank": {**BANK, "account_number": number}},
            },
        ),
        (
            UpdateVendor,
            {
                "expected_version": 1,
                "data": {"name": "Synthetic vendor", "bank": {**BANK, "account_number": number}},
            },
        ),
        (DebitAccountUpdate, {"expected_version": 0, "data": {**DEBIT, "account_number": number}}),
    ]:
        with pytest.raises(ValidationError, match="exactly 10 digits"):
            schema.model_validate(command)


async def test_legacy_short_bank_is_readable_but_cannot_be_resubmitted(
    client, organisation, sessions
):
    await sign_in(client, organisation["people"]["staff"])
    req = await draft(client, organisation, "10")
    legacy = content("10")
    legacy["vendor"].update(**BANK, account_number="00123")
    async with sessions() as s, s.begin():
        row = await s.get(Requisition, UUID(req["id"]))
        row.content = Content.model_validate(legacy).model_dump(mode="json")
    path = f"/api/v1/requisitions/{req['id']}"
    read = await client.get(path)
    assert read.status_code == 200 and read.json()["content"]["vendor"]["account_number"] == "00123"
    challenge = await client.post(
        path + "/signing-challenges", json={"expected_version": req["version"], "action": "submit"}
    )
    assert challenge.status_code == 422 and "exactly 10 digits" in challenge.text
    legacy["vendor"]["account_number"] = "0000000123"
    corrected = await client.put(
        path + "/draft", json={"expected_version": req["version"], "content": legacy}
    )
    assert corrected.status_code == 200
    assert corrected.json()["content"]["vendor"]["account_number"] == "0000000123"


async def test_selecting_a_legacy_vendor_cannot_bypass_bank_validation(
    client, organisation, sessions
):
    from app.vendors.models import BeneficiaryVersion, Vendor, VendorVersion

    vendor_id, version_id, bank_id = uuid4(), uuid4(), uuid4()
    async with sessions() as s, s.begin():
        s.add(
            Vendor(
                id=vendor_id,
                entity_id=UUID(organisation["entity_id"]),
                created_by=organisation["people"]["hod"]["id"],
                current_version_id=version_id,
                version=1,
            )
        )
        await s.flush()
        s.add(BeneficiaryVersion(id=bank_id, vendor_id=vendor_id, **BANK, account_number="00123"))
        await s.flush()
        s.add(
            VendorVersion(
                id=version_id,
                vendor_id=vendor_id,
                number=1,
                data={"name": "Synthetic legacy vendor"},
                beneficiary_id=bank_id,
            )
        )
    await sign_in(client, organisation["people"]["staff"])
    response = await client.post(
        "/api/v1/requisitions",
        json={
            "entity_id": organisation["entity_id"],
            "creation_key": str(uuid4()),
            "content": content("10"),
            "vendor_selection": {"id": str(vendor_id), "expected_version": 1},
        },
    )
    assert response.status_code == 422 and "10-digit" in response.text
    assert "00123" not in response.text
