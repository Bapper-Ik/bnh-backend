from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import AuditDetails, record_event
from app.exports.models import Export
from app.exports.projection import signing
from app.exports.schemas import Snapshot
from app.requisitions.models import Requisition, Revision
from app.requisitions.schemas import Content
from app.requisitions.service import content_digest
from app.transfers.models import CompanyDebitAccount
from app.transfers.schemas import DebitAccount, TransferDetails

TRANSFER_CONSENT = (
    "I authorise the system to place this approval signature, my name and the approval date "
    "on the bank transfer request for the exact amount and bank details shown here."
)


async def details(s: AsyncSession, req: Requisition) -> TransferDetails:
    revision = await s.get(Revision, req.current_revision_id)
    assert revision
    account = await s.get(CompanyDebitAccount, req.entity_id, populate_existing=True)
    vendor = Content.model_validate(revision.content).vendor
    missing = []
    if not account:
        missing.append("Company debit account and bank branch address")
    for label, value in [
        ("Beneficiary bank", vendor.bank_name),
        ("Beneficiary account name", vendor.account_name),
        ("Beneficiary account number", vendor.account_number),
    ]:
        if not value:
            missing.append(label)
    return TransferDetails(
        debit=DebitAccount.model_validate(account.data) if account else None,
        debit_version=account.version if account else 0,
        beneficiary_bank=vendor.bank_name,
        beneficiary_name=vendor.account_name,
        beneficiary_account=vendor.account_number,
        amount=format(revision.total, ".2f"),
        missing=missing,
    )


async def enqueue(
    s: AsyncSession,
    req: Requisition,
    transfer: TransferDetails,
    signature: dict[str, Any],
    signer_role: str,
) -> Export:
    """Called in the approval transaction, after signature validation and version update."""
    assert req.state == "APPROVED" and req.current_revision_id
    rev = await s.get(Revision, req.current_revision_id)
    assert rev
    approved_at = datetime.fromisoformat(str(signature["at"]))
    snapshot = Snapshot(
        reference=req.reference,
        requisition_id=req.id,
        revision=rev.number,
        request_version=req.version,
        state="APPROVED",
        current_state="APPROVED",
        requester=rev.requester_name,
        department=rev.department_name,
        company=rev.entity_name,
        authority=rev.authority,
        route=rev.routing_explanation,
        policy=rev.policy_version,
        content=Content.model_validate(rev.content),
        total=format(rev.total, ".2f"),
        redacted_fields=[],
        as_of=approved_at,
        signatures=[signing(signer_role, signature)],
        evidence=[],
        board=[],
        include_board=False,
        transfer=transfer,
    )
    payload = snapshot.model_dump(mode="json")
    row = Export(
        id=uuid4(),
        requisition_id=req.id,
        revision_id=rev.id,
        requested_by=req.requester_id,
        idempotency_key=uuid4(),
        command_digest=content_digest({"revision": str(rev.id), "document": "bank_transfer"}),
        document_type="bank_transfer",
        request_version=req.version,
        revision_number=rev.number,
        include_board=False,
        includes_bank=True,
        snapshot=payload,
        snapshot_digest=content_digest(payload),
        template_version="bank-transfer-v1",
        filename=f"{req.reference}-revision-{rev.number}-bank-transfer.pdf",
        available_at=approved_at,
        status="failed" if transfer.missing else "pending",
        last_error="transfer_details_missing" if transfer.missing else None,
    )
    s.add(row)
    await s.flush()
    await record_event(
        s,
        action="requisition.transfer.queued",
        actor_id=UUID(str(signature["actor_id"])),
        resource_id=req.id,
        entity_id=req.entity_id,
        details=AuditDetails(resource_type="export", export_id=row.id, revision_id=rev.id),
    )
    return row
