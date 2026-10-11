from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, Record


class Export(Record, Base):
    __tablename__ = "requisition_exports"
    __table_args__ = (UniqueConstraint("requested_by", "idempotency_key"),)
    requisition_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.requisitions.id", ondelete="RESTRICT")
    )
    revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("custodian.requisition_revisions.id", ondelete="RESTRICT")
    )
    requested_by: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.identities.id", ondelete="RESTRICT")
    )
    idempotency_key: Mapped[UUID]
    command_digest: Mapped[str]
    request_version: Mapped[int]
    revision_number: Mapped[int]
    include_board: Mapped[bool]
    includes_bank: Mapped[bool]
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB)
    snapshot_digest: Mapped[str]
    document_type: Mapped[str] = mapped_column(default="requisition", server_default="requisition")
    template_version: Mapped[str]
    filename: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None]
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    storage_key: Mapped[str | None]
    object_version: Mapped[str | None]
    file_digest: Mapped[str | None]
    byte_size: Mapped[int | None]
    renderer_version: Mapped[str | None]
    font_version: Mapped[str | None]
    last_error: Mapped[str | None]
