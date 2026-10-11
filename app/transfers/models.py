from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CompanyDebitAccount(Base):
    __tablename__ = "company_debit_accounts"
    entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.entities.id", ondelete="RESTRICT"), primary_key=True
    )
    version: Mapped[int] = mapped_column(default=1)
    data: Mapped[dict[str, object]] = mapped_column(JSONB)


class DepartmentDebitAccount(Base):
    __tablename__ = "department_debit_accounts"
    department_id: Mapped[UUID] = mapped_column(
        ForeignKey("custodian.departments.id", ondelete="RESTRICT"), primary_key=True
    )
    version: Mapped[int] = mapped_column(default=1)
    data: Mapped[dict[str, object]] = mapped_column(JSONB)
