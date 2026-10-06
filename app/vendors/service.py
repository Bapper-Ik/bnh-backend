from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import AuditDetails, record_event
from app.core.errors import DomainError
from app.identity.service import Actor
from app.organisation.service import membership
from app.vendors.models import BeneficiaryVersion, Vendor, VendorVersion
from app.vendors.schemas import BankDetails, VendorData, VendorView


async def scoped_vendor(session: AsyncSession, vendor_id: UUID, actor: Actor) -> Vendor:
    vendor = await session.scalar(select(Vendor).where(Vendor.id == vendor_id).with_for_update())
    if not vendor:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Vendor not found.", 404)
    try:
        await membership(session, actor.id, vendor.entity_id)
    except DomainError as exc:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Vendor not found.", 404) from exc
    return vendor


def can_read_bank(vendor: Vendor, actor: Actor) -> bool:
    return not actor.account.read_only and (
        vendor.created_by == actor.id or "vendor:read_sensitive" in actor.account.permissions
    )


def require_write(vendor: Vendor | None, actor: Actor) -> None:
    if actor.account.read_only or (
        vendor
        and vendor.created_by != actor.id
        and "vendor:update" not in actor.account.permissions
    ):
        raise DomainError("ACCESS_DENIED", "You cannot maintain this vendor.", 403)
    if vendor and not can_read_bank(vendor, actor):
        raise DomainError(
            "ACCESS_DENIED", "Bank-detail access is required to replace a vendor version.", 403
        )


async def add_version(
    session: AsyncSession, vendor: Vendor, data: VendorData, actor: Actor
) -> VendorVersion:
    beneficiary = None
    if data.bank:
        beneficiary = BeneficiaryVersion(id=uuid4(), vendor_id=vendor.id, **data.bank.model_dump())
        session.add(beneficiary)
        await session.flush()
        await record_event(
            session,
            action="vendor.beneficiary_created",
            actor_id=actor.id,
            resource_id=beneficiary.id,
            entity_id=vendor.entity_id,
        )
    version = VendorVersion(
        id=vendor.current_version_id,
        vendor_id=vendor.id,
        number=vendor.version,
        data=data.model_dump(mode="json", exclude={"bank"}),
        beneficiary_id=beneficiary.id if beneficiary else None,
    )
    session.add(version)
    await session.flush()
    await record_event(
        session,
        action="vendor.created" if vendor.version == 1 else "vendor.updated",
        actor_id=actor.id,
        resource_id=vendor.id,
        entity_id=vendor.entity_id,
        details=AuditDetails(content_digest=None),
    )
    return version


async def view(
    session: AsyncSession, vendor: Vendor, version: VendorVersion, actor: Actor
) -> VendorView:
    data = VendorData.model_validate(version.data)
    allowed = can_read_bank(vendor, actor)
    beneficiary = (
        await session.get(BeneficiaryVersion, version.beneficiary_id)
        if version.beneficiary_id and allowed
        else None
    )
    if beneficiary:
        data.bank = BankDetails(
            bank_name=beneficiary.bank_name,
            account_number=beneficiary.account_number,
            account_name=beneficiary.account_name,
        )
    return VendorView(
        can_update=allowed
        and (vendor.created_by == actor.id or "vendor:update" in actor.account.permissions)
        and version.number == vendor.version,
        id=vendor.id,
        entity_id=vendor.entity_id,
        version=version.number,
        name=data.name,
        registration_id=data.registration_id,
        bank_details_state="unknown"
        if not version.beneficiary_id
        else "supplied"
        if allowed
        else "restricted",
        version_id=version.id,
        data=data,
        beneficiary_version_id=version.beneficiary_id if allowed else None,
    )
