import io
from uuid import UUID, uuid4

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app.exports.models import Export
from app.identity.models import Account
from app.requisitions.models import Decision
from app.transfers.models import CompanyDebitAccount
from app.transfers.words import naira_words
from tests.exports.test_exports import generate
from tests.requisitions.test_workflow import content, draft, sign_in, signed

DEBIT = dict(
    bank_name="Synthetic debit bank",
    branch_address="Test branch, Abuja",
    account_name="Synthetic company account",
    account_number="0001234567",
    company_address="Test company address",
)


async def configure(sessions, org):
    async with sessions() as s, s.begin():
        s.add(CompanyDebitAccount(entity_id=UUID(org["entity_id"]), version=1, data=DEBIT))


async def submitted(client, org, amount="248000.15"):
    person = org["people"]["staff"]
    await sign_in(client, person)
    req = await draft(client, org, amount)
    body = content(amount)
    body["vendor"].update(
        bank_name="Synthetic beneficiary bank",
        account_name="Synthetic supplier",
        account_number="0012345678",
    )
    r = await client.put(
        f"/api/v1/requisitions/{req['id']}/draft",
        json={"expected_version": req["version"], "content": body},
    )
    assert r.status_code == 200, r.text
    req, _ = await signed(client, r.json(), person, "submit")
    return req


@pytest.mark.parametrize(
    "value,expected",
    [
        ("248000.15", "Two Hundred and Forty-Eight Thousand Naira and Fifteen Kobo Only"),
        ("24000000", "Twenty-Four Million Naira Only"),
        ("100000000.01", "One Hundred Million Naira and One Kobo Only"),
        ("0", "Zero Naira Only"),
    ],
)
def test_words(value, expected):
    assert naira_words(value) == expected


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "1.001", "1000000000000000"])
def test_invalid_amounts(value):
    with pytest.raises(ValueError):
        naira_words(value)


async def test_approval_queues_once_with_exact_signature_and_frozen_bank_data(
    exports, organisation, sessions, tmp_path
):
    client, _, _ = exports
    await configure(sessions, organisation)
    req = await submitted(client, organisation)
    await sign_in(client, organisation["people"]["hod"])
    req, command = await signed(client, req, organisation["people"]["hod"], "approve")
    assert req["state"] == "APPROVED"
    assert (
        await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=command)
    ).status_code == 200
    async with sessions() as s, s.begin():
        rows = (
            await s.scalars(select(Export).where(Export.requisition_id == UUID(req["id"])))
        ).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.document_type == "bank_transfer" and row.status == "pending"
        decision = await s.scalar(select(Decision).where(Decision.revision_id == row.revision_id))
        signature = row.snapshot["signatures"][0]
        assert signature["strokes"] == decision.signature["strokes"] == command["strokes"]
        assert signature["name"] == organisation["people"]["hod"]["name"]
        assert signature["at"] == decision.signature["at"]
        assert "bank transfer request" in signature["statement"]
        assert row.snapshot["transfer"]["beneficiary_account"] == "0012345678"
        assert row.snapshot["transfer"]["debit"]["account_number"] == "0001234567"
        profile = await s.get(CompanyDebitAccount, UUID(organisation["entity_id"]))
        profile.data = {**DEBIT, "account_number": "9999999999"}
        profile.version += 1
        item = {"id": str(row.id)}
    await sign_in(client, organisation["people"]["staff"])
    await generate(exports, sessions, item)
    view = (await client.get("/api/v1/exports/" + item["id"])).json()
    assert view["status"] == "ready", view
    response = await client.get("/api/v1/exports/" + item["id"] + "/content")
    assert response.status_code == 200
    pdf = PdfReader(io.BytesIO(response.content))
    text = "\n".join(p.extract_text() for p in pdf.pages)
    assert len(pdf.pages) == 1
    assert "PAYMENT INSTRUCTION" in text and "248,000.15" in text
    assert text.count(req["reference"]) == 1
    assert "revision" not in text.lower()
    assert "Signed electronically" not in text
    assert "This instruction does not confirm" not in text
    assert "Page 1" not in text
    assert "0001234567" in text and "9999999999" not in text
    assert "Synthetic hod" in text and "Head of Department" in text
    assert "Synthetic staff" not in text
    # Vector approval strokes are rendered as PDF paths, not a typed-name substitute.
    assert b" m " in pdf.pages[0].get_contents().get_data()
    (tmp_path / "transfer-preview.pdf").write_bytes(response.content)
    await sign_in(client, organisation["people"]["other_hod"])
    assert (await client.get("/api/v1/exports/" + item["id"] + "/content")).status_code == 404


async def test_changed_debit_account_invalidates_signing_challenge(exports, organisation, sessions):
    client, _, _ = exports
    await configure(sessions, organisation)
    req = await submitted(client, organisation)
    person = organisation["people"]["hod"]
    await sign_in(client, person)
    intent = {"expected_version": req["version"], "action": "approve", "reason": ""}
    challenge = (
        await client.post(f"/api/v1/requisitions/{req['id']}/signing-challenges", json=intent)
    ).json()
    assert challenge["transfer_details"]["debit"]["account_number"] == "0001234567"
    async with sessions() as s, s.begin():
        row = await s.get(CompanyDebitAccount, UUID(organisation["entity_id"]))
        row.data = {**DEBIT, "account_number": "9999999999"}
        row.version += 1
    command = {
        **intent,
        "challenge_id": challenge["id"],
        "idempotency_key": str(uuid4()),
        "signer_name": person["name"],
        "consent": True,
        "strokes": [[{"x": 0.1, "y": 0.2}, {"x": 0.2, "y": 0.5}, {"x": 0.3, "y": 0.2}]],
    }
    r = await client.post(f"/api/v1/requisitions/{req['id']}/actions", json=command)
    assert r.status_code == 409 and r.json()["code"] == "SIGNATURE_INVALID", r.text
    assert (await client.get(f"/api/v1/requisitions/{req['id']}")).json()[
        "state"
    ] == "PENDING_AUTHORITY"


async def test_missing_bank_details_do_not_undo_approval_or_allow_unsigned_repair(
    exports, organisation, sessions
):
    client, _, _ = exports
    req = await submitted(client, organisation)
    await sign_in(client, organisation["people"]["hod"])
    req, _ = await signed(client, req, organisation["people"]["hod"], "approve")
    await sign_in(client, organisation["people"]["staff"])
    items = (await client.get(f"/api/v1/requisitions/{req['id']}/exports")).json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["last_error"] == "transfer_details_missing" and not item["can_retry"]
    await configure(sessions, organisation)
    assert (await client.post("/api/v1/exports/" + item["id"] + "/retry")).status_code == 409
    assert (await client.get(f"/api/v1/requisitions/{req['id']}")).json()["state"] == "APPROVED"


async def test_bank_profile_permissions_validation_and_version(exports, organisation, sessions):
    client, _, _ = exports
    person = organisation["people"]["staff"]
    await sign_in(client, person)
    path = f"/api/v1/organisation/entities/{organisation['entity_id']}/debit-account"
    assert (await client.get(path)).status_code == 403
    async with sessions() as s, s.begin():
        account = await s.scalar(select(Account).where(Account.identity_id == person["id"]))
        account.permissions = ["organisation:manage"]
    assert (await client.get(path)).json() == {"version": 0, "data": None}
    assert (
        await client.put(path, json={"expected_version": 0, "data": {**DEBIT, "bank_name": " "}})
    ).status_code == 422
    reply = await client.put(path, json={"expected_version": 0, "data": DEBIT})
    assert reply.status_code == 200 and reply.json()["version"] == 1, reply.text
    assert reply.json()["data"]["account_number"] == "0001234567"
    assert (await client.put(path, json={"expected_version": 0, "data": DEBIT})).status_code == 409


@pytest.mark.parametrize("outcome", ["APPROVE", "REJECT", "DEFER", "CONDITIONAL_APPROVE"])
async def test_board_transfer_uses_chairman_only_on_unconditional_approval(
    exports, organisation, sessions, outcome
):
    from tests.board.test_board import act, data, save, upload

    client, _, _ = exports
    people = organisation["people"]
    await configure(sessions, organisation)
    req = await submitted(client, organisation, "600000000")
    await sign_in(client, people["secretary"])
    case = await upload(client, await save(client, req, data(outcome=outcome)))
    case, _, _ = await act(client, case, people["secretary"], "board_submit")
    async with sessions() as s:
        assert not await s.scalar(select(Export).where(Export.requisition_id == UUID(req["id"])))
    await sign_in(client, people["chairman"])
    case, path, command = await act(client, case, people["chairman"], "board_confirm")
    assert (await client.post(path + "/actions", json=command)).status_code == 200
    async with sessions() as s:
        rows = (
            await s.scalars(select(Export).where(Export.requisition_id == UUID(req["id"])))
        ).all()
        assert len(rows) == (1 if outcome == "APPROVE" else 0)
        if rows:
            row = rows[0]
            assert len(row.snapshot["signatures"]) == 1 and row.snapshot["board"] == []
            signature = row.snapshot["signatures"][0]
            assert (
                signature["name"] == people["chairman"]["name"]
                and signature["strokes"] == command["strokes"]
            )
            assert signature["label"] == "Board Chairman"
            item = {"id": str(row.id)}
    if outcome == "APPROVE":
        await sign_in(client, people["staff"])
        await generate(exports, sessions, item)
        result = await client.get("/api/v1/exports/" + item["id"] + "/content")
        assert result.status_code == 200
        text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(result.content)).pages)
        assert "Synthetic chairman" in text and "Synthetic secretary" not in text


@pytest.mark.parametrize("role,amount", [("chief_of_staff", "24000000"), ("md", "248000000")])
async def test_senior_approval_preserved_when_fonts_are_missing_and_retry_uses_same_signature(
    exports, organisation, sessions, tmp_path, monkeypatch, role, amount
):
    client, app, _ = exports
    await configure(sessions, organisation)
    req = await submitted(client, organisation, amount)
    await sign_in(client, organisation["people"][role])
    req, command = await signed(client, req, organisation["people"][role], "approve")
    await sign_in(client, organisation["people"]["staff"])
    item = (await client.get(f"/api/v1/requisitions/{req['id']}/exports")).json()["items"][0]
    from app.exports import render as pdf_render

    directory = pdf_render.font_directory()
    monkeypatch.setattr(pdf_render, "FONT_DIRECTORY", tmp_path)
    await generate(exports, sessions, item)
    failed = (await client.get("/api/v1/exports/" + item["id"])).json()
    assert failed["status"] == "failed" and failed["last_error"] == "fonts_unavailable"
    assert (await client.get(f"/api/v1/requisitions/{req['id']}")).json()["state"] == "APPROVED"
    async with sessions() as s:
        before = (await s.get(Export, UUID(item["id"]))).snapshot
        assert before["signatures"][0]["label"] == role
        assert before["signatures"][0]["strokes"] == command["strokes"]
    monkeypatch.setattr(pdf_render, "FONT_DIRECTORY", directory)
    assert (await client.post("/api/v1/exports/" + item["id"] + "/retry")).status_code == 200
    await generate(exports, sessions, item)
    async with sessions() as s:
        row = await s.get(Export, UUID(item["id"]))
        assert row.status == "ready" and row.snapshot == before


def test_isolated_signature_marks_are_not_dropped(pdf_fonts):
    from datetime import UTC, datetime

    from app.exports.render import render
    from tests.exports.test_render import sample

    now = datetime.now(UTC)
    snapshot = sample(
        state="APPROVED",
        revision=1,
        transfer={
            "debit": DEBIT,
            "beneficiary_bank": "Synthetic bank",
            "beneficiary_name": "Supplier",
            "beneficiary_account": "0012345678",
            "amount": "1.01",
        },
        signatures=[
            {
                "label": "hod",
                "name": "Synthetic approver",
                "at": now.isoformat(),
                "strokes": [[{"x": 0.1, "y": 0.2}], [{"x": 0.2, "y": 0.4}], [{"x": 0.3, "y": 0.2}]],
            }
        ],
    )
    pdf, _, _ = render(snapshot, str(uuid4()), "a" * 64, now, pdf_fonts)
    page = PdfReader(io.BytesIO(pdf)).pages[0]
    # Three isolated points must remain visible circles, not an empty signature area.
    assert page.get_contents().get_data().count(b" c\n") >= 12
