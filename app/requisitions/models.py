from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, Record


class Requisition(Record, Base):
    __tablename__ = "requisitions"
    __table_args__ = (UniqueConstraint("requester_id", "creation_key"),)
    reference: Mapped[str] = mapped_column(unique=True)
    requester_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.identities.id", ondelete="RESTRICT")
    )
    entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.entities.id", ondelete="RESTRICT")
    )
    department_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.departments.id", ondelete="RESTRICT")
    )
    creation_key: Mapped[UUID]
    creation_digest: Mapped[str]
    state: Mapped[str] = mapped_column(default="DRAFT", server_default="DRAFT")
    version: Mapped[int] = mapped_column(default=1, server_default="1")
    content: Mapped[dict[str, object]] = mapped_column(JSONB)
    context: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, server_default="{}")
    total: Mapped[Decimal] = mapped_column(Numeric(17, 2))
    current_revision_id: Mapped[UUID | None]
    revision_number: Mapped[int] = mapped_column(default=0, server_default="0")


class Revision(Record, Base):
    __tablename__ = "requisition_revisions"
    __table_args__ = (UniqueConstraint("requisition_id", "number"),)
    requisition_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.requisitions.id", ondelete="RESTRICT")
    )
    number: Mapped[int]
    content: Mapped[dict[str, object]] = mapped_column(JSONB)
    context: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, server_default="{}")
    total: Mapped[Decimal] = mapped_column(Numeric(17, 2))
    requester_name: Mapped[str]
    department_name: Mapped[str]
    entity_name: Mapped[str]
    authority: Mapped[str]
    approver_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("custodian.identities.id", ondelete="RESTRICT")
    )
    policy_version: Mapped[str]
    routing_explanation: Mapped[str]
    content_digest: Mapped[str]
    signature: Mapped[dict[str, object]] = mapped_column(JSONB)


class Decision(Record, Base):
    __tablename__ = "decisions"
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.requisition_revisions.id", ondelete="RESTRICT"), unique=True
    )
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.identities.id", ondelete="RESTRICT")
    )
    action: Mapped[str]
    reason: Mapped[str]
    signature: Mapped[dict[str, object]] = mapped_column(JSONB)
    content_digest: Mapped[str]


class SigningChallenge(Record, Base):
    __tablename__ = "signing_challenges"
    requisition_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.requisitions.id", ondelete="RESTRICT")
    )
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.identities.id", ondelete="RESTRICT")
    )
    action: Mapped[str]
    expected_version: Mapped[int]
    content_digest: Mapped[str]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed: Mapped[bool] = mapped_column(default=False, server_default="false")


class CommandResult(Record, Base):
    __tablename__ = "command_results"
    __table_args__ = (UniqueConstraint("actor_id", "idempotency_key"),)
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.identities.id", ondelete="RESTRICT")
    )
    idempotency_key: Mapped[UUID]
    payload_digest: Mapped[str]
    resource_id: Mapped[UUID]
    result: Mapped[dict[str, object]] = mapped_column(JSONB)
