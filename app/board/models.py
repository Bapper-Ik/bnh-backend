from uuid import UUID

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, Record


class Resolution(Record, Base):
    __tablename__ = "board_resolutions"
    __table_args__ = (UniqueConstraint("revision_id", "number"),)
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.requisition_revisions.id", ondelete="RESTRICT")
    )
    number: Mapped[int]
    predecessor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("custodian.board_resolutions.id", ondelete="RESTRICT")
    )
    kind: Mapped[str]
    recorded_by: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.identities.id", ondelete="RESTRICT")
    )
    data: Mapped[dict[str, object]] = mapped_column(JSONB)
    evidence_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("custodian.attachments.id", ondelete="RESTRICT")
    )
    signature: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, server_default="{}")


class ChairmanDecision(Record, Base):
    __tablename__ = "board_chairman_decisions"
    resolution_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.board_resolutions.id", ondelete="RESTRICT"), unique=True
    )
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.identities.id", ondelete="RESTRICT")
    )
    action: Mapped[str]
    reason: Mapped[str]
    outcome: Mapped[str]
    signature: Mapped[dict[str, object]] = mapped_column(JSONB)
