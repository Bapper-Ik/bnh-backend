from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, Record


class Entity(Record, Base):
    __tablename__ = "entities"
    name: Mapped[str] = mapped_column(unique=True)
    code: Mapped[str] = mapped_column(unique=True, default=lambda: uuid4().hex[:16])
    kind: Mapped[str] = mapped_column(default="subsidiary", server_default="subsidiary")
    active: Mapped[bool] = mapped_column(default=True, server_default="true")


class Department(Record, Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("entity_id", "name"), UniqueConstraint("entity_id", "code"))
    entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.entities.id", ondelete="RESTRICT")
    )
    name: Mapped[str]
    code: Mapped[str] = mapped_column(default=lambda: uuid4().hex[:16])
    active: Mapped[bool] = mapped_column(default=True, server_default="true")


class Membership(Record, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("identity_id", "entity_id"),)
    identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.identities.id", ondelete="RESTRICT")
    )
    entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.entities.id", ondelete="RESTRICT")
    )
    department_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.departments.id", ondelete="RESTRICT")
    )
    active: Mapped[bool] = mapped_column(default=True, server_default="true")


class Office(Record, Base):
    __tablename__ = "offices"
    identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.identities.id", ondelete="RESTRICT")
    )
    entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.entities.id", ondelete="RESTRICT")
    )
    department_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("custodian.departments.id", ondelete="RESTRICT")
    )
    role: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True, server_default="true")
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authorisation_reference: Mapped[str]
