from pydantic import BaseModel, Field, model_validator

from app.identity.schemas import Command


class DebitAccount(Command):
    bank_name: str = Field(min_length=1, max_length=150)
    branch_address: str = Field(min_length=1, max_length=500)
    account_name: str = Field(min_length=1, max_length=250)
    account_number: str = Field(min_length=1, max_length=100)
    company_address: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def meaningful(self) -> "DebitAccount":
        for field in type(self).model_fields:
            value = getattr(self, field).strip()
            if field != "company_address" and not value:
                raise ValueError(
                    "Bank, branch address, account name and account number are required"
                )
            if any(ord(c) < 32 and c not in "\n\r" for c in value):
                raise ValueError("Control characters are not allowed")
            setattr(self, field, value)
        return self


class DebitAccountUpdate(Command):
    expected_version: int = Field(ge=0)
    data: DebitAccount


class DebitAccountView(BaseModel):
    version: int
    data: DebitAccount | None


class TransferDetails(BaseModel):
    debit: DebitAccount | None = None
    debit_version: int = 0
    beneficiary_bank: str
    beneficiary_name: str
    beneficiary_account: str
    amount: str
    missing: list[str] = Field(default_factory=list)
