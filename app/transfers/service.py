from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import AuditDetails, record_event
from app.authority.self_approval import hod_self_approval
from app.exports.models import Export
from app.exports.projection import signing
from app.exports.schemas import Snapshot
from app.requisitions.models import Requisition, Revision
from app.requisitions.schemas import Content
from app.requisitions.service import content_digest
from app.transfers.models import CompanyDebitAccount, DepartmentDebitAccount
from app.transfers.schemas import DebitAccount, TransferDetails
from app.vendors.models import BeneficiaryVersion, Vendor, VendorVersion

TRANSFER_CONSENT = (
    "I authorise the system to place this approval signature, my name and the approval date "
    "on the bank transfer request for the exact amount and bank details shown here."
)


async def details(s: AsyncSession, req: Requisition) -> TransferDetails:
    revision = await s.get(Revision, req.current_revision_id)
    assert revision
    department_debit = hod_self_approval(req, revision)
    account = (
        await s.get(DepartmentDebitAccount, req.department_id, populate_existing=True)
        if department_debit
        else await s.get(CompanyDebitAccount, req.entity_id, populate_existing=True)
    )
    vendor = Content.model_validate(revision.content).vendor
    # The requester may only see a redacted vendor snapshot. Resolve the exact
    # version they selected, never today's vendor account. These values are shown
    # to the approver and bound into their fresh transfer-signing challenge.
    context = revision.context.get("context", {})
    if (
        isinstance(context, dict)
        and context.get("bank_details_state") == "restricted"
        and context.get("vendor_version_id")
        and context.get("vendor_id")
        and not any((vendor.bank_name, vendor.account_name, vendor.account_number))
    ):
        bank = await s.scalar(
            select(BeneficiaryVersion)
            .join(VendorVersion, VendorVersion.beneficiary_id == BeneficiaryVersion.id)
            .join(Vendor, Vendor.id == VendorVersion.vendor_id)
            .where(
                VendorVersion.id == UUID(str(context["vendor_version_id"])),
                Vendor.id == UUID(str(context["vendor_id"])),
                Vendor.entity_id == req.entity_id,
                BeneficiaryVersion.vendor_id == Vendor.id,
            )
        )
        if bank:
            vendor.bank_name = bank.bank_name
            vendor.account_name = bank.account_name
            vendor.account_number = bank.account_number
    missing = []
    if not account:
        missing.append(
            "Department sub-account and bank branch address"
            if department_debit
            else "Company debit account and bank branch address"
        )
    for label, value in [
        ("Beneficiary bank", vendor.bank_name),
        ("Beneficiary account name", vendor.account_name),
        ("Beneficiary account number", vendor.account_number),
    ]:
        if not value:
            missing.append(label)
    return TransferDetails(
        debit_source="department" if department_debit else "company",
        department_id=req.department_id if department_debit else None,
        department_name=revision.department_name if department_debit else None,
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
