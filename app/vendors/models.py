from uuid import UUID

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, Record


class Vendor(Record, Base):
    __tablename__ = "vendors"
    entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.entities.id", ondelete="RESTRICT")
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.identities.id", ondelete="RESTRICT")
    )
    version: Mapped[int] = mapped_column(default=1, server_default="1")
    current_version_id: Mapped[UUID]


class BeneficiaryVersion(Record, Base):
    __tablename__ = "beneficiary_versions"
    vendor_id: Mapped[UUID] = mapped_column(ForeignKey("custodian.vendors.id", ondelete="RESTRICT"))
    bank_name: Mapped[str]
    account_number: Mapped[str]
    account_name: Mapped[str]


class VendorVersion(Record, Base):
    __tablename__ = "vendor_versions"
    __table_args__ = (UniqueConstraint("vendor_id", "number"),)
    vendor_id: Mapped[UUID] = mapped_column(ForeignKey("custodian.vendors.id", ondelete="RESTRICT"))
    number: Mapped[int]
    data: Mapped[dict[str, object]] = mapped_column(JSONB)
    beneficiary_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("custodian.beneficiary_versions.id", ondelete="RESTRICT")
    )
