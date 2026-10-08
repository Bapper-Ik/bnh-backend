from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, Record


class AuditEvent(Record, Base):
    __tablename__ = "audit_events"
    event_key: Mapped[str] = mapped_column(String(200), unique=True)
    action: Mapped[str] = mapped_column(String(100))
    actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("custodian.identities.id", ondelete="RESTRICT")
    )
    actor_type: Mapped[str] = mapped_column(String(20))
    resource_id: Mapped[UUID | None]
    entity_id: Mapped[UUID | None]
    details: Mapped[dict[str, object]] = mapped_column(JSONB)
    correlation_id: Mapped[UUID]


class OutboxItem(Record, Base):
    __tablename__ = "outbox_items"
    __table_args__ = (UniqueConstraint("event_id", "destination"),)
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.audit_events.id", ondelete="RESTRICT")
    )
    destination: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
