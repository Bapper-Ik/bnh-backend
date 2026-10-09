from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, TypeAdapter, field_validator, model_validator

from app.authority.policy import calculate_lines, exact_decimal
from app.history.schemas import NextAction
from app.identity.schemas import Command


class CostLine(Command):
    description: str = Field(min_length=1, max_length=500)
    quantity: str = Field(max_length=40)
    unit_price: str = Field(max_length=40)

    @field_validator("description")
    @classmethod
    def meaningful(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Item description cannot be blank")
        return value.strip()

    @model_validator(mode="after")
    def amounts(self) -> "CostLine":
        exact_decimal(self.quantity, 4, positive=True)
        exact_decimal(self.unit_price, 2)
        return self


class VendorInfo(Command):
    name: str = Field(default="", max_length=250)
    contact_person: str = Field(default="", max_length=180)
    phone: str = Field(default="", max_length=1024)
    email: str = Field(default="", max_length=320)
    address: str = Field(default="", max_length=1000)
    registration_id: str = Field(default="", max_length=150)
    bank_name: str = Field(default="", max_length=150)
    account_number: str = Field(default="", max_length=100)
    account_name: str = Field(default="", max_length=250)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        return str(TypeAdapter(EmailStr).validate_python(value)) if value.strip() else ""

    @model_validator(mode="after")
    def bank_complete(self) -> "VendorInfo":
        values = [self.bank_name.strip(), self.account_number.strip(), self.account_name.strip()]
        if any(values) and not all(values):
            raise ValueError("Supply all three bank fields or leave all empty")
        self.bank_name, self.account_number, self.account_name = values
        return self


class VendorSelection(Command):
    id: UUID
    expected_version: int = Field(ge=1)


class Content(Command):
    vendor: VendorInfo = Field(default_factory=VendorInfo)
    description: str = Field(default="", max_length=5000)
    location: str = Field(default="", max_length=500)
    start_date: date | None = None
    completion_date: date | None = None
    payment_terms: str = Field(default="", max_length=2000)
    warranty: str = Field(default="", max_length=2000)
    currency: Literal["NGN"] = "NGN"
    lines: list[CostLine] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def consistent(self) -> "Content":
        if self.start_date and self.completion_date and self.completion_date < self.start_date:
            raise ValueError("Completion date must not precede start date")
        calculate_lines([(line.quantity, line.unit_price) for line in self.lines])
        return self


class CreateRequest(Command):
    entity_id: UUID
    creation_key: UUID
    content: Content
    vendor_selection: VendorSelection | None = None


class UpdateRequest(Command):
    expected_version: int = Field(ge=1)
    content: Content
    vendor_selection: VendorSelection | None = None


class StartRevision(Command):
    expected_version: int = Field(ge=1)
    idempotency_key: UUID


class Intent(Command):
    expected_version: int = Field(ge=1)
    action: Literal["submit", "approve", "reject", "return"]
    reason: str = Field(default="", max_length=2000)


class Point(Command):
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)


class SignedAction(Intent):
    challenge_id: UUID
    idempotency_key: UUID
    signer_name: str = Field(min_length=2, max_length=180)
    consent: Literal[True]
    strokes: list[list[Point]] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def drawing(self) -> "SignedAction":
        count = sum(len(stroke) for stroke in self.strokes)
        if count < 3 or count > 4000:
            raise ValueError("Draw a signature with 3 to 4000 points")
        return self


class ChallengeView(BaseModel):
    id: UUID
    content_digest: str
    expires_at: str
    statement: str
    total: str
    authority: str | None = None
    routing_explanation: str | None = None


class RequestView(BaseModel):
    oversight_only: bool = False
    id: UUID
    reference: str
    entity_id: UUID
    requester_name: str
    entity_name: str
    department_name: str
    state: str
    version: int
    total: str
    created_at: str
    required_authority: str | None
    routing_explanation: str | None
    submission_blocker: str | None = None
    decision_blocker: str | None = None
    viewing_revision: int | None = None
    content: Content
    available_actions: list[str]
    revision_number: int
    redacted_fields: list[str] = Field(default_factory=list)
    next_action: NextAction | None = None
    history: list[dict[str, object]]
