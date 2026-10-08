from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, Record


class Notification(Record, Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("event_id", "recipient_id", "kind"),)
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.audit_events.id", ondelete="RESTRICT")
    )
    recipient_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.identities.id", ondelete="RESTRICT")
    )
    requisition_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.requisitions.id", ondelete="RESTRICT")
    )
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.requisition_revisions.id", ondelete="RESTRICT")
    )
    resolution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("custodian.board_resolutions.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(30))
    template: Mapped[str] = mapped_column(String(50))
    template_version: Mapped[str] = mapped_column(default="v1", server_default="v1")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_status: Mapped[str] = mapped_column(default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None]
    recipient_address: Mapped[str | None] = mapped_column(String(320))
    sender_address: Mapped[str | None] = mapped_column(String(320))
    link_origin: Mapped[str | None] = mapped_column(String(500))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_id: Mapped[UUID | None]
    last_error: Mapped[str | None] = mapped_column(String(50))
