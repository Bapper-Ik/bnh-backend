from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.audit.models import AuditEvent, OutboxItem
from app.audit.service import AuditDetails, record_event, register_events
from app.core.database import Identity


async def test_event_and_delivery_are_atomic(sessions):
    person_id = uuid4()
    async with sessions() as s, s.begin():
        s.add(Identity(id=person_id, display_name="Synthetic audit actor"))
        await s.flush()
        event = await record_event(
            s, action="identity.created", actor_id=person_id, resource_id=person_id
        )
        event_id = event.id
    async with sessions() as s:
        assert await s.get(AuditEvent, event_id)
        item = await s.scalar(select(OutboxItem).where(OutboxItem.event_id == event_id))
        assert item.status == "pending"


async def test_failed_event_rolls_back_business_record(sessions):
    person_id = uuid4()
    with pytest.raises(IntegrityError):
        async with sessions() as s, s.begin():
            s.add(Identity(id=person_id, display_name="Must roll back"))
            await s.flush()
            await record_event(
                s, action="identity.created", actor_id=uuid4(), resource_id=person_id
            )
    async with sessions() as s:
        assert await s.get(Identity, person_id) is None


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE custodian.audit_events SET action='tampered'",
        "DELETE FROM custodian.audit_events",
        "TRUNCATE custodian.audit_events CASCADE",
        "ALTER TABLE custodian.audit_events DISABLE TRIGGER ALL",
    ],
)
async def test_runtime_cannot_rewrite_history(sessions, statement):
    with pytest.raises(DBAPIError):
        async with sessions() as s, s.begin():
            await s.execute(text(statement))


async def test_duplicate_event_key_cannot_commit_twice(sessions):
    key = str(uuid4())
    async with sessions() as s, s.begin():
        await record_event(s, action="audit.integrity_check.success", actor_id=None, event_key=key)
    with pytest.raises(IntegrityError):
        async with sessions() as s, s.begin():
            await record_event(
                s, action="audit.integrity_check.success", actor_id=None, event_key=key
            )
    async with sessions() as s:
        assert (
            len((await s.scalars(select(AuditEvent).where(AuditEvent.event_key == key))).all()) == 1
        )


def test_registry_and_payload_reject_duplicates_and_secrets():
    with pytest.raises(ValueError):
        register_events("identity.created")
    with pytest.raises(ValidationError):
        AuditDetails(password="secret", account_number="0000000000")


async def test_rejected_transaction_records_only_safe_failure(sessions):
    from app.audit.service import audited_transaction
    from app.core.errors import DomainError

    resource_id, correlation = uuid4(), uuid4()
    with pytest.raises(DomainError):
        async with audited_transaction(
            sessions, actor_id=None, correlation_id=correlation, resource_id=resource_id
        ) as s:
            s.add(Identity(id=resource_id, display_name="Must not persist"))
            await s.flush()
            await record_event(
                s,
                action="identity.created",
                actor_id=None,
                resource_id=resource_id,
                correlation_id=correlation,
            )
            raise DomainError("ACCESS_DENIED", "private password or bank data must not reach audit")
    async with sessions() as s:
        assert await s.get(Identity, resource_id) is None
        events = (
            await s.scalars(select(AuditEvent).where(AuditEvent.correlation_id == correlation))
        ).all()
        assert len(events) == 1
        assert events[0].action == "access.denied.failure"
        assert events[0].details == {
            "outcome": "denied",
            "resource_type": "access",
            "changed_fields": [],
        }
        assert await s.scalar(select(OutboxItem).where(OutboxItem.event_id == events[0].id))


async def test_archive_delivery_changes_do_not_mutate_event(sessions):
    async with sessions() as s, s.begin():
        event = await record_event(s, action="audit.protection_check.success", actor_id=None)
        event_id, original = event.id, dict(event.details)
    async with sessions() as s, s.begin():
        item = await s.scalar(select(OutboxItem).where(OutboxItem.event_id == event_id))
        item.status = "retry"
        item.attempts = 1
    async with sessions() as s:
        assert (await s.get(AuditEvent, event_id)).details == original


async def test_outbox_failure_rolls_back_event_and_business_write(sessions):
    person_id = uuid4()
    with pytest.raises(IntegrityError):
        async with sessions() as s, s.begin():
            s.add(Identity(id=person_id, display_name="Outbox rollback"))
            await s.flush()
            event = await record_event(s, action="identity.created", actor_id=person_id)
            event_id = event.id
            s.add(OutboxItem(event_id=event_id, destination="archive"))
            await s.flush()
    async with sessions() as s:
        assert await s.get(Identity, person_id) is None
        assert await s.get(AuditEvent, event_id) is None
        assert not await s.scalar(select(OutboxItem).where(OutboxItem.event_id == event_id))


async def test_concurrent_duplicate_events_commit_one_transition(sessions):
    import asyncio

    key = str(uuid4())
    ids = [uuid4(), uuid4()]

    async def transition(person_id):
        try:
            async with sessions() as s, s.begin():
                s.add(Identity(id=person_id, display_name="Concurrent synthetic actor"))
                await s.flush()
                await record_event(s, action="identity.created", actor_id=person_id, event_key=key)
            return True
        except IntegrityError:
            return False

    assert sorted(await asyncio.gather(*(transition(i) for i in ids))) == [False, True]
    async with sessions() as s:
        assert len((await s.scalars(select(Identity).where(Identity.id.in_(ids)))).all()) == 1
        assert (
            len((await s.scalars(select(AuditEvent).where(AuditEvent.event_key == key))).all()) == 1
        )


def test_digest_and_changed_fields_cannot_carry_arbitrary_secrets():
    with pytest.raises(ValidationError):
        AuditDetails(content_digest="secret password")
    with pytest.raises(ValidationError):
        AuditDetails(changed_fields=["bank account: 0000000000"])
    with pytest.raises(ValueError):
        register_events("synthetic.duplicate", "synthetic.duplicate")
