from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.authority.policy import exact_decimal
from app.evidence.router import AttachmentView
from app.identity.schemas import Command
from app.requisitions.schemas import Point, RequestView


class ResolutionData(Command):
    meeting_date: date | None = None
    board_name: str = Field(default="", max_length=250)
    reference: str = Field(default="", max_length=200)
    decision_text: str = Field(default="", max_length=10000)
    outcome: Literal["APPROVE", "REJECT", "DEFER", "CONDITIONAL_APPROVE"] = "APPROVE"
    authorised_amount: str | None = Field(default=None, max_length=40)
    currency: Literal["NGN"] = "NGN"
    correction_summary: str = Field(default="", max_length=2000)
    conditions: str = Field(default="", max_length=5000)
    attendance: str = Field(default="", max_length=5000)
    quorum_attested: bool = False
    quorum_basis: str = Field(default="", max_length=2000)
    evidence_type: Literal["resolution", "minutes_extract"] = "resolution"

    @model_validator(mode="after")
    def outcome_amount(self) -> "ResolutionData":
        if self.outcome in {"REJECT", "DEFER"}:
            self.authorised_amount = None
        return self

    @field_validator("authorised_amount")
    @classmethod
    def amount(cls, value: str | None) -> str | None:
        if value is not None:
            exact_decimal(value, 2)
        return value


class SaveResolution(Command):
    expected_version: int = Field(ge=1)
    idempotency_key: UUID
    data: ResolutionData


class BoardIntent(Command):
    expected_version: int = Field(ge=1)
    action: Literal["board_submit", "board_confirm", "board_return"]
    reason: str = Field(default="", max_length=2000)


class BoardSignedAction(BoardIntent):
    challenge_id: UUID
    idempotency_key: UUID
    signer_name: str = Field(min_length=2, max_length=180)
    consent: Literal[True]
    strokes: list[list[Point]] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def drawing(self) -> "BoardSignedAction":
        if not 3 <= sum(len(stroke) for stroke in self.strokes) <= 4000:
            raise ValueError("Draw a signature with 3 to 4000 points")
        return self


class ResolutionView(BaseModel):
    id: UUID
    number: int
    predecessor_id: UUID | None
    kind: str
    data: ResolutionData
    status: str
    recorded_at: str
    submitted_at: str | None
    secretary_name: str | None
    chairman_name: str | None
    decided_at: str | None
    return_reason: str | None
    evidence: AttachmentView | None


class BoardCase(BaseModel):
    request: RequestView
    records: list[ResolutionView]
    available_actions: list[str]
    blocker: str | None = None
    uploads_enabled: bool
