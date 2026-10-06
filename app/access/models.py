from uuid import UUID

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, Record


class ReviewGrant(Record, Base):
    __tablename__ = "review_grants"
    __table_args__ = (UniqueConstraint("identity_id", "entity_id"),)
    identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.identities.id", ondelete="RESTRICT")
    )
    entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.entities.id", ondelete="RESTRICT")
    )
    active: Mapped[bool] = mapped_column(default=True, server_default="true")
