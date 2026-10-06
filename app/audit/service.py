from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditEvent, OutboxItem
from app.core.errors import DomainError

EVENTS: set[str] = set()


def register_events(*names: str) -> None:
    if len(set(names)) != len(names) or EVENTS.intersection(names):
        raise ValueError("Duplicate event registration")
    EVENTS.update(names)


register_events(
    "access.denied.failure",
    "access.permission_change.success",
    "access.permission_change.failure",
    "identity.created",
    "identity.updated",
    "auth.signed_in",
    "auth.signed_out",
    "auth.recovered",
    "auth.recovery_issued",
    "auth.recovery_failed",
    "auth.reauthenticated",
    "auth.sessions_revoked",
    "auth.failed",
    "organisation.created",
    "organisation.updated",
    "office.assignment_failed",
    "office.assigned",
    "office.revoked",
    "vendor.created",
    "vendor.updated",
    "evidence.uploaded",
    "signature.challenged",
    "requisition.created",
    "requisition.updated",
    "requisition.submitted",
    "requisition.approved",
    "requisition.rejected",
    "requisition.returned",
    "board.recorded",
    "board.confirmed",
    "board.returned",
    "audit.integrity_check.success",
    "audit.integrity_check.failure",
    "audit.protection_check.success",
    "audit.protection_check.failure",
)


class AuditDetails(BaseModel):
    """Identifiers/enums only: no arbitrary bank, password or signature values."""

    model_config = ConfigDict(extra="forbid")
    revision_id: UUID | None = None
    resolution_id: UUID | None = None
    department_id: UUID | None = None
    office: Literal["hod", "chief_of_staff", "md", "secretary", "chairman", "board"] | None = None
    policy_version: Literal["bnh-doa-v1"] | None = None
    outcome: Literal[
        "success", "denied", "approved", "rejected", "returned", "deferred", "conditional"
    ] = "success"
    content_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    resource_type: (
        Literal[
            "identity",
            "auth",
            "organisation",
            "office",
            "vendor",
            "evidence",
            "signature",
            "requisition",
            "board",
            "audit",
            "access",
        ]
        | None
    ) = None
    changed_fields: list[
        Literal[
            "account_state", "membership", "appointment", "content", "state", "password", "session"
        ]
    ] = Field(default_factory=list, max_length=20)


async def record_event(
    session: AsyncSession,
    *,
    action: str,
    actor_id: UUID | None,
    resource_id: UUID | None = None,
    entity_id: UUID | None = None,
    details: AuditDetails | None = None,
    correlation_id: UUID | None = None,
    event_key: str | None = None,
) -> AuditEvent:
    if action not in EVENTS:
        raise ValueError("Unregistered event")
    details = details or AuditDetails()
    if details.resource_type is None:
        details = AuditDetails.model_validate(
            {**details.model_dump(), "resource_type": action.split(".")[0]}
        )
    event = AuditEvent(
        id=uuid4(),
        event_key=event_key or str(uuid4()),
        action=action,
        actor_id=actor_id,
        actor_type="staff" if actor_id else "system",
        resource_id=resource_id,
        entity_id=entity_id,
        details=details.model_dump(mode="json", exclude_none=True),
        correlation_id=correlation_id or uuid4(),
    )
    session.add(event)
    await session.flush()
    session.add(OutboxItem(event_id=event.id, destination="archive"))
    await session.flush()
    return event


@asynccontextmanager
async def audited_transaction(
    sessions: async_sessionmaker[AsyncSession],
    *,
    actor_id: UUID | None,
    correlation_id: UUID,
    resource_id: UUID | None = None,
    entity_id: UUID | None = None,
) -> AsyncIterator[AsyncSession]:
    """Rollback an expected rejection, then persist only its safe failure envelope.

    IDs must come from trusted server context. Exception text and command bodies
    are deliberately excluded. If the failure audit cannot persist, propagate
    that error; never pretend an unrecorded action succeeded.
    """
    try:
        async with sessions() as session, session.begin():
            yield session
    except DomainError:
        async with sessions() as failure_session, failure_session.begin():
            await record_event(
                failure_session,
                action="access.denied.failure",
                actor_id=actor_id,
                resource_id=resource_id,
                entity_id=entity_id,
                correlation_id=correlation_id,
                details=AuditDetails(outcome="denied"),
            )
        raise
