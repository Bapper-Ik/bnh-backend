from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class HistoryEntry(BaseModel):
    id: str
    type: str
    at: datetime
    actor: str
    actor_id: UUID | None = None
    revision: int | None = None
    reason: str | None = None
    authority: str | None = None
    routing_explanation: str | None = None
    policy_version: str | None = None
    signature_id: str | None = None
    digest: str | None = None
    resolution_id: UUID | None = None
    resolution_number: int | None = None
    resolution_reference: str | None = None
    meeting_date: date | None = None
    evidence_id: UUID | None = None
    evidence_filename: str | None = None


class HistoryPage(BaseModel):
    items: list[HistoryEntry]
    total: int
    limit: int
    offset: int


class NextAction(BaseModel):
    label: str
    actor_name: str | None = None
    blocked_reason: str | None = None
