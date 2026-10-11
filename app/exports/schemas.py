from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.identity.schemas import Command
from app.requisitions.schemas import Content, Point
from app.transfers.schemas import TransferDetails


class ExportCommand(Command):
    expected_version: int = Field(ge=1)
    revision: int | None = Field(default=None, ge=1)
    include_board: bool = False
    idempotency_key: UUID


class SigningRecord(BaseModel):
    label: str
    name: str
    at: str
    statement: str = ""
    reason: str = ""
    digest: str = ""
    signature_id: str = ""
    strokes: list[list[Point]] = Field(default_factory=list)


class EvidenceReference(BaseModel):
    id: str
    filename: str
    digest: str


class BoardRecord(BaseModel):
    number: int
    kind: str
    record_id: str
    predecessor_id: str | None
    recorded_at: str
    meeting_date: str
    reference: str
    board_name: str
    outcome: str
    decision: str
    amount: str | None
    conditions: str
    attendance: str
    quorum_basis: str
    correction: str
    evidence: EvidenceReference | None
    signatures: list[SigningRecord]


class Snapshot(BaseModel):
    transfer: TransferDetails | None = None
    reference: str
    requisition_id: UUID
    revision: int
    request_version: int
    state: str
    current_state: str
    requester: str
    department: str
    company: str
    authority: str
    route: str
    policy: str
    content: Content
    total: str
    redacted_fields: list[str]
    as_of: datetime
    signatures: list[SigningRecord]
    evidence: list[EvidenceReference]
    board: list[BoardRecord]
    include_board: bool


class ExportView(BaseModel):
    document_type: str = "requisition"
    id: UUID
    revision: int
    request_version: int
    include_board: bool
    filename: str
    status: str
    created_at: datetime
    generated_at: datetime | None
    template_version: str
    file_digest: str | None
    byte_size: int | None
    attempts: int
    last_error: str | None
    can_retry: bool


class ExportPage(BaseModel):
    items: list[ExportView]
    total: int
    limit: int
    offset: int
    can_include_board: bool
    unavailable_reason: str | None
