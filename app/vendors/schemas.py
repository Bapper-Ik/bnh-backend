from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.identity.schemas import Command


class BankDetails(Command):
    bank_name: str = Field(min_length=1, max_length=150)
    account_number: str = Field(min_length=1, max_length=100)
    account_name: str = Field(min_length=1, max_length=250)

    @field_validator("bank_name", "account_number", "account_name")
    @classmethod
    def meaningful(cls, value: str) -> str:
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("Supply complete bank details without control characters")
        return value.strip()


class VendorData(Command):
    name: str = Field(min_length=2, max_length=250)
    contact_person: str = Field(default="", max_length=180)
    phones: list[str] = Field(default_factory=list, max_length=10)
    email: EmailStr | None = None
    address: str = Field(default="", max_length=1000)
    registration_id: str = Field(default="", max_length=150)
    bank: BankDetails | None = None

    @field_validator("name")
    @classmethod
    def meaningful_name(cls, value: str) -> str:
        if len(value.strip()) < 2:
            raise ValueError("Supply a vendor name")
        return value.strip()

    @field_validator("phones")
    @classmethod
    def supplied_phones(cls, values: list[str]) -> list[str]:
        if any(not x.strip() or len(x) > 100 for x in values):
            raise ValueError("Supply nonblank phone numbers of at most 100 characters")
        return [x.strip() for x in values]


class CreateVendor(Command):
    entity_id: UUID
    data: VendorData


class UpdateVendor(Command):
    expected_version: int = Field(ge=1)
    data: VendorData


class VendorSummary(BaseModel):
    id: UUID
    entity_id: UUID
    version: int
    name: str
    registration_id: str
    bank_details_state: Literal["unknown", "supplied", "restricted"]
    verification: Literal["not_verified"] = "not_verified"


class VendorView(VendorSummary):
    can_update: bool
    version_id: UUID
    data: VendorData
    beneficiary_version_id: UUID | None


class VendorPage(BaseModel):
    items: list[VendorSummary]
    total: int
    limit: int
    offset: int
