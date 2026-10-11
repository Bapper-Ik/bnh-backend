"""Private evidence ownership contract shared by access and upload services."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, Record


class Attachment(Record, Base):
    __tablename__ = "attachments"
    requisition_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.requisitions.id", ondelete="RESTRICT")
    )
    uploaded_by: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.identities.id", ondelete="RESTRICT")
    )
    upload_key: Mapped[UUID | None] = mapped_column(unique=True)
    kind: Mapped[str]
    filename: Mapped[str]
    media_type: Mapped[str]
    byte_size: Mapped[int]
    digest: Mapped[str]
    storage_key: Mapped[str] = mapped_column(unique=True)
    object_version: Mapped[str]
    validation_state: Mapped[str] = mapped_column(default="pending", server_default="pending")
    detached: Mapped[bool] = mapped_column(default=False, server_default="false")
    frozen: Mapped[bool] = mapped_column(default=False, server_default="false")


class StagedUpload(Record, Base):
    __tablename__ = "staged_uploads"
    uploaded_by: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.identities.id", ondelete="RESTRICT")
    )
    entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.entities.id", ondelete="RESTRICT")
    )
    creation_key: Mapped[UUID]
    filename: Mapped[str]
    media_type: Mapped[str]
    digest: Mapped[str]
    data: Mapped[bytes] = mapped_column(LargeBinary)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
