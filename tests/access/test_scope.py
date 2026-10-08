from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.access.service import project_content, require_action
from app.access_app import create_app
from app.core.database import Identity
from app.core.errors import DomainError
from app.evidence.models import Attachment
from app.identity.models import Account, LoginSession
from app.identity.service import Actor, digest, hasher
from app.organisation.models import Department, Entity, Membership, Office
from app.requisitions.models import Requisition, Revision

PASSWORD = "Synthetic-access-password-2026"


@pytest.fixture
async def scope_data(sessions):
    people, requests, files = {}, {}, {}
    async with sessions() as s, s.begin():
        companies = [Entity(name=f"Synthetic scope company {uuid4()}") for _ in range(2)]
        s.add_all(companies)
        await s.flush()
        departments = [Department(entity_id=e.id, name="Operations") for e in companies]
        s.add_all(departments)
        await s.flush()
        for role in (
            "owner",
            "other",
            "outside",
            "hod",
            "md",
            "secretary",
            "chairman",
            "reviewer",
            "admin",
        ):
            identity = Identity(display_name=f"Synthetic {role}")
            s.add(identity)
            await s.flush()
            account = Account(
                identity_id=identity.id,
                email=f"{uuid4()}@example.com",
                password_hash=hasher.hash(PASSWORD),
                permissions=["office_assignment:manage", "staff:manage"] if role == "admin" else [],
            )
            s.add(account)
            company = 1 if role == "outside" else 0
            s.add(
                Membership(
                    identity_id=identity.id,
                    entity_id=companies[company].id,
                    department_id=departments[company].id,
                )
            )
            if role in {"hod", "md", "secretary", "chairman"}:
                s.add(
                    Office(
                        identity_id=identity.id,
                        entity_id=companies[0].id,
                        department_id=departments[0].id if role == "hod" else None,
                        role=role,
                        valid_from=datetime.now(UTC) - timedelta(days=1),
                        authorisation_reference="Synthetic approved scope",
                    )
                )
            people[role] = (identity, account)
        await s.flush()
        for key, owner, company, authority in (
            ("mine", "owner", 0, "hod"),
            ("other", "other", 0, "hod"),
            ("outside", "outside", 1, "hod"),
            ("board", "owner", 0, "board"),
        ):
            request = Requisition(
                id=uuid4(),
                reference=f"SYNTHETIC-{uuid4()}",
                requester_id=people[owner][0].id,
                entity_id=companies[company].id,
                department_id=departments[company].id,
                creation_key=uuid4(),
                creation_digest="synthetic",
                state="AWAITING_BOARD_RESOLUTION" if authority == "board" else "PENDING_AUTHORITY",
                version=2,
                content={
                    "vendor": {
                        "name": "Synthetic vendor",
                        "bank_name": "Private test bank",
                        "account_number": "0000000001",
                        "account_name": "Synthetic beneficiary",
                    }
                },
                total=Decimal("100.00"),
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
                requester_name=people[owner][0].display_name,
                department_name="Operations",
                entity_name=companies[company].name,
                authority=authority,
                approver_id=people["hod"][0].id if authority == "hod" else None,
                policy_version="bnh-doa-v1",
                routing_explanation="Synthetic policy",
                content_digest="a" * 64,
                context={
                    "route": {
                        "secretary_id": str(people["secretary"][0].id),
                        "chairman_id": str(people["chairman"][0].id),
                    }
                }
                if authority == "board"
                else {},
                signature={},
            )
            s.add(revision)
            await s.flush()
            request.current_revision_id = revision.id
            attachment = Attachment(
                requisition_id=request.id,
                uploaded_by=request.requester_id,
                kind="board_resolution" if key == "board" else "request_support",
                filename="synthetic.pdf",
                media_type="application/pdf",
                byte_size=1,
                digest="a" * 64,
                storage_key=str(uuid4()),
                object_version="synthetic",
                validation_state="pending",
            )
            s.add(attachment)
            await s.flush()
            requests[key], files[key] = request, attachment
        return {"people": people, "requests": requests, "files": files, "entity": companies[0].id}


@pytest.fixture
async def access_client(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app),
            base_url="http://test",
            headers={"origin": "http://localhost:5173"},
        ) as client:
            yield client


async def login(client, data, role):
    account = data["people"][role][1]
    response = await client.post(
        "/api/v1/auth/login", json={"email": account.email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    client.headers["x-csrf-token"] = client.cookies.get("custodian_csrf")


async def test_requester_lists_and_details_share_exact_scope(access_client, scope_data):
    await login(access_client, scope_data, "owner")
    listing = await access_client.get("/api/v1/access/requisitions?limit=1")
    assert listing.status_code == 200
    assert listing.json()["total"] == 2
    assert len(listing.json()["items"]) == 1
    assert "Private test bank" not in listing.text
    for key in ("mine", "board"):
        assert (
            await access_client.get(f"/api/v1/access/requisitions/{scope_data['requests'][key].id}")
        ).status_code == 200
    for key in ("other", "outside"):
        assert (
            await access_client.get(f"/api/v1/access/requisitions/{scope_data['requests'][key].id}")
        ).status_code == 404
    assert (
        await access_client.get(f"/api/v1/access/attachments/{scope_data['files']['mine'].id}")
    ).status_code == 200
    assert (
        await access_client.get(f"/api/v1/access/attachments/{scope_data['files']['outside'].id}")
    ).status_code == 404
    # Owning the financial request does not imply access to private Board evidence.
    assert (
        await access_client.get(f"/api/v1/access/attachments/{scope_data['files']['board'].id}")
    ).status_code == 404


async def test_seniority_and_admin_flags_do_not_confer_financial_access(access_client, scope_data):
    for role in ("md", "admin", "other"):
        await login(access_client, scope_data, role)
        response = await access_client.get(
            f"/api/v1/access/requisitions/{scope_data['requests']['mine'].id}",
            headers={"x-role": "hod", "x-permissions": "requisition:approve"},
        )
        assert response.status_code == 404
    await login(access_client, scope_data, "hod")
    response = await access_client.get(
        f"/api/v1/access/requisitions/{scope_data['requests']['mine'].id}"
    )
    assert "approve" in response.json()["actions"]
    assert (await access_client.get("/api/v1/access/requisitions")).json()["total"] == 2
    assert (
        await access_client.get(
            f"/api/v1/access/requisitions/{scope_data['requests']['outside'].id}"
        )
    ).status_code == 404


async def test_readonly_review_is_explicit_scoped_and_never_mutating(
    access_client, scope_data, sessions
):
    await login(access_client, scope_data, "reviewer")
    assert (await access_client.get("/api/v1/access/requisitions")).json()["total"] == 0
    await login(access_client, scope_data, "admin")
    body = {
        "identity_id": str(scope_data["people"]["reviewer"][0].id),
        "entity_id": str(scope_data["entity"]),
    }
    assert (await access_client.post("/api/v1/access/review-grants", json=body)).status_code == 200
    await login(access_client, scope_data, "reviewer")
    listing = await access_client.get("/api/v1/access/requisitions")
    assert listing.json()["total"] == 3
    assert all(set(item["actions"]) == {"read", "export"} for item in listing.json()["items"])
    assert (
        await access_client.get(f"/api/v1/access/attachments/{scope_data['files']['board'].id}")
    ).status_code == 404
    async with sessions() as s, s.begin():
        identity, account = scope_data["people"]["reviewer"]
        stored = await s.get(Account, account.id)
        auth = await s.scalar(
            select(LoginSession).where(
                LoginSession.token_hash == digest(access_client.cookies.get("custodian_session"))
            )
        )
        actor = Actor(stored, identity, auth)
        request = await s.get(Requisition, scope_data["requests"]["mine"].id)
        for action in (
            "approve",
            "reject",
            "return",
            "edit",
            "submit",
            "board_record",
            "board_confirm",
            "board_return",
            "attachment_upload",
        ):
            with pytest.raises(DomainError):
                await require_action(s, request, actor, action)
        projected, redacted = project_content(request.content, actor)
        assert projected["vendor"]["account_number"] == ""
        assert redacted == ["vendor.bank_details"]
        assert request.content["vendor"]["account_number"] == "0000000001"
    await login(access_client, scope_data, "admin")
    assert (
        await access_client.post("/api/v1/access/review-grants", json={**body, "active": False})
    ).status_code == 200
    await login(access_client, scope_data, "reviewer")
    assert (await access_client.get("/api/v1/access/requisitions")).json()["total"] == 0


async def test_appointment_revocation_changes_list_and_detail_together(
    access_client, scope_data, sessions
):
    await login(access_client, scope_data, "hod")
    assert (await access_client.get("/api/v1/access/requisitions")).json()["total"] == 2
    async with sessions() as s, s.begin():
        office = await s.scalar(
            select(Office).where(Office.identity_id == scope_data["people"]["hod"][0].id)
        )
        office.active = False
    assert (await access_client.get("/api/v1/access/requisitions")).json()["total"] == 0
    assert (
        await access_client.get(f"/api/v1/access/requisitions/{scope_data['requests']['mine'].id}")
    ).status_code == 404


async def test_board_roles_only_receive_their_board_cases(access_client, scope_data):
    for role in ("secretary", "chairman"):
        await login(access_client, scope_data, role)
        listing = (await access_client.get("/api/v1/access/requisitions")).json()
        assert listing["total"] == 1
        assert listing["items"][0]["requisition_id"] == str(scope_data["requests"]["board"].id)
        attachment = await access_client.get(
            f"/api/v1/access/attachments/{scope_data['files']['board'].id}"
        )
        assert attachment.status_code == 200
        assert "storage_key" not in attachment.text
        assert (
            await access_client.get(f"/api/v1/access/attachments/{scope_data['files']['mine'].id}")
        ).status_code == 404


async def test_read_grants_cannot_self_grant_or_mix_with_financial_offices(
    access_client, scope_data
):
    await login(access_client, scope_data, "admin")
    for role, status in (("admin", 403), ("hod", 409)):
        response = await access_client.post(
            "/api/v1/access/review-grants",
            json={
                "identity_id": str(scope_data["people"][role][0].id),
                "entity_id": str(scope_data["entity"]),
            },
        )
        assert response.status_code == status
