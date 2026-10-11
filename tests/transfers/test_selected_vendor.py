"""A hidden vendor account must still reach fresh approval and the owner's letter."""

import io
from uuid import UUID, uuid4

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app.exports.models import Export
from app.requisitions.models import Revision
from tests.exports.test_exports import generate
from tests.requisitions.test_workflow import content, sign_in, signed
from tests.transfers.test_transfers import configure

BANK = {
    "bank_name": "Synthetic selected bank",
    "account_name": "Synthetic selected beneficiary",
    "account_number": "0009876543",
}


async def selected(client, org, amount="248000.15", bank=BANK):
    await sign_in(client, org["people"]["other_hod"])
    data = {"name": "Synthetic shared supplier", "bank": bank}
    response = await client.post(
        "/api/v1/vendors", json={"entity_id": org["entity_id"], "data": data}
    )
    assert response.status_code == 201, response.text
    vendor = response.json()
    await sign_in(client, org["people"]["staff"])
    hidden = (await client.get("/api/v1/vendors/" + vendor["id"])).json()
    assert hidden["data"]["bank"] is None
    body = {
        "entity_id": org["entity_id"],
        "creation_key": str(uuid4()),
        "content": content(amount),
        "vendor_selection": {"id": vendor["id"], "expected_version": 1},
    }
    response = await client.post("/api/v1/requisitions", json=body)
    assert response.status_code == 201, response.text
    req = response.json()
    assert req["content"]["vendor"]["account_number"] == ""
    assert (await client.post("/api/v1/requisitions", json=body)).json() == req
    return req, vendor, data


async def change_bank(client, org, vendor, data):
    await sign_in(client, org["people"]["other_hod"])
    response = await client.patch(
        "/api/v1/vendors/" + vendor["id"],
        json={
            "expected_version": vendor["version"],
            "data": {**data, "bank": {**BANK, "account_number": "9999999999"}},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    "role,amount",
    [
        ("hod", "248000.15"),
        ("chief_of_staff", "24000000"),
        ("md", "248000000"),
        ("chairman", "600000000"),
    ],
)
async def test_shared_vendor_approval_download_uses_selected_bank_version(
    exports, organisation, sessions, role, amount
):
    client, _, _ = exports
    people = organisation["people"]
    await configure(sessions, organisation)
    req, vendor, data = await selected(client, organisation, amount)
    # A later master edit must not change the selected version, even before submission.
    await change_bank(client, organisation, vendor, data)
    await sign_in(client, people["staff"])
    path = "/api/v1/requisitions/" + req["id"]
    req["content"]["description"] = "Shared vendor purchase"
    saved = await client.put(
        path + "/draft", json={"expected_version": req["version"], "content": req["content"]}
    )
    assert saved.status_code == 200, saved.text
    req = saved.json()
    challenge = await client.post(
        path + "/signing-challenges", json={"expected_version": req["version"], "action": "submit"}
    )
    assert challenge.json()["transfer_details"] is None
    req, command = await signed(client, req, people["staff"], "submit")
    assert (await client.post(path + "/actions", json=command)).json()["content"]["vendor"][
        "account_number"
    ] == ""
    async with sessions() as s:
        rev = await s.scalar(select(Revision).where(Revision.requisition_id == UUID(req["id"])))
        original_content, original_context = rev.content, rev.context
        assert original_context["context"]["vendor_version_id"] == vendor["version_id"]
        # This also covers existing pending requests created before the fix.
        assert original_context["context"]["beneficiary_version_id"] is None
    if role == "chairman":
        from tests.board.test_board import act, save, upload
        from tests.board.test_board import data as board_data

        await sign_in(client, people["secretary"])
        case = await upload(client, await save(client, req, board_data(outcome="APPROVE")))
        case, _, _ = await act(client, case, people["secretary"], "board_submit")
        await sign_in(client, people[role])
        case, approval_path, command = await act(client, case, people[role], "board_confirm")
    else:
        await sign_in(client, people[role])
        challenge = await client.post(
            path + "/signing-challenges",
            json={"expected_version": req["version"], "action": "approve"},
        )
        assert challenge.status_code == 201, challenge.text
        details = challenge.json()["transfer_details"]
        assert details["beneficiary_account"] == BANK["account_number"]
        assert details["beneficiary_name"] == BANK["account_name"]
        assert details["beneficiary_bank"] == BANK["bank_name"]
        assert details["missing"] == []
        req, command = await signed(client, req, people[role], "approve")
        approval_path = path
    assert (await client.post(approval_path + "/actions", json=command)).status_code == 200
    async with sessions() as s:
        rows = (
            await s.scalars(select(Export).where(Export.requisition_id == UUID(req["id"])))
        ).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.status == "pending" and row.snapshot["transfer"]["missing"] == []
        assert row.snapshot["transfer"]["beneficiary_account"] == BANK["account_number"]
        assert row.snapshot["signatures"][0]["strokes"] == command["strokes"]
        rev = await s.get(Revision, row.revision_id)
        assert rev.content == original_content and rev.context == original_context
        item = {"id": str(row.id)}
    await generate(exports, sessions, item)
    await sign_in(client, people["staff"])
    listed = (await client.get(path + "/exports")).json()["items"]
    assert len(listed) == 1 and listed[0]["status"] == "ready"
    result = await client.get("/api/v1/exports/" + item["id"] + "/content")
    assert result.status_code == 200 and result.headers["content-type"] == "application/pdf"
    assert "attachment;" in result.headers["content-disposition"]
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(result.content)).pages)
    for value in BANK.values():
        assert value in text
    assert "9999999999" not in text
    assert people[role]["name"] in text
    assert (await client.get(path)).json()["content"]["vendor"]["account_number"] == ""
    await sign_in(client, people["other_hod"])
    assert (await client.get("/api/v1/exports/" + item["id"] + "/content")).status_code == 404


@pytest.mark.parametrize("replacement", ["manual", "reselect", "originally_unknown"])
async def test_transfer_does_not_resolve_stale_selection_or_newly_added_bank(
    exports, organisation, sessions, replacement
):
    client, _, _ = exports
    people = organisation["people"]
    await configure(sessions, organisation)
    req, vendor, data = await selected(
        client, organisation, bank=None if replacement == "originally_unknown" else BANK
    )
    vendor = await change_bank(client, organisation, vendor, data)
    await sign_in(client, people["staff"])
    path = "/api/v1/requisitions/" + req["id"]
    update = {"expected_version": req["version"], "content": req["content"]}
    if replacement == "manual":
        update["content"]["vendor"] = {
            "name": "Manual beneficiary",
            **BANK,
            "account_number": "0011223344",
        }
    elif replacement == "reselect":
        update["vendor_selection"] = {"id": vendor["id"], "expected_version": vendor["version"]}
    saved = await client.put(path + "/draft", json=update)
    assert saved.status_code == 200, saved.text
    req, _ = await signed(client, saved.json(), people["staff"], "submit")
    await sign_in(client, people["hod"])
    req, _ = await signed(client, req, people["hod"], "approve")
    async with sessions() as s:
        row = await s.scalar(select(Export).where(Export.requisition_id == UUID(req["id"])))
        expected = {"manual": "0011223344", "reselect": "9999999999", "originally_unknown": ""}[
            replacement
        ]
        assert row.snapshot["transfer"]["beneficiary_account"] == expected
        assert row.status == ("failed" if replacement == "originally_unknown" else "pending")
