import asyncio
import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import Select, and_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.errors import DomainError
from app.evidence.storage import Storage
from app.exports.models import Export
from app.exports.render import RenderFailure, font_directory, render
from app.exports.schemas import Snapshot
from app.exports.service import allowed, audit
from app.identity.models import Account
from app.notifications.service import Recipient
from app.requisitions.models import Requisition, Revision
from app.requisitions.service import content_digest

Renderer = Callable[[Snapshot, str, str, datetime, Path], tuple[bytes, str, str]]
logger = logging.getLogger("custodian.exports")


def scoped(actor: Recipient) -> Select[tuple[Export]]:
    return (
        select(Export)
        .join(Requisition, Requisition.id == Export.requisition_id)
        .outerjoin(Revision, Revision.id == Requisition.current_revision_id)
        .where(allowed(actor))
    )


async def claim_job(
    sessions: async_sessionmaker[AsyncSession], export_id: UUID | None = None
) -> tuple[UUID, UUID] | None:
    async with sessions() as s, s.begin():
        now = datetime.now(UTC)
        row = await s.scalar(
            select(Export)
            .where(
                or_(
                    and_(Export.status == "pending", Export.available_at <= now),
                    and_(Export.status == "running", Export.lease_until <= now),
                ),
                Export.id == export_id if export_id else true(),
            )
            .order_by(Export.available_at, Export.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not row:
            return None
        row.status = "running"
        row.attempts += 1
        row.lease_until, row.lease_token = now + timedelta(minutes=2), uuid4()
        return row.id, row.lease_token


async def permitted(s: AsyncSession, row: Export) -> bool:
    account = await s.scalar(select(Account).where(Account.identity_id == row.requested_by))
    return bool(
        account
        and account.active
        and not account.password_pending
        and await s.scalar(scoped(Recipient(account)).where(Export.id == row.id))
    )


async def process_claim(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage: Storage,
    claim: tuple[UUID, UUID],
    renderer: Renderer = render,
) -> None:
    async with sessions() as s, s.begin():
        row = await s.get(Export, claim[0])
        if not row or row.status != "running" or row.lease_token != claim[1]:
            return
        may_render = await permitted(s, row)
        snapshot = row.snapshot
        snapshot_digest = row.snapshot_digest
        template_version = row.template_version
        attempts = row.attempts
    failure = None
    result = None
    generated_at = datetime.now(UTC)
    if not may_render:
        failure = "access_changed"
    elif attempts > 3:
        failure = "retry_limit_reached"
    else:
        try:
            if content_digest(snapshot) != snapshot_digest:
                raise RenderFailure("snapshot_integrity_failed")
            data, renderer_version, font_version = await run_in_threadpool(
                partial(renderer, template_version=template_version)
                if renderer is render
                else renderer,
                Snapshot.model_validate(snapshot),
                str(claim[0]),
                snapshot_digest,
                generated_at,
                font_directory(),
            )
            digest = hashlib.sha256(data).hexdigest()
            key = f"exports/{claim[0]}/{claim[1]}/{digest}.pdf"
            object_version = await storage.put(key, data, "application/pdf")
            result = (key, object_version, digest, len(data), renderer_version, font_version)
        except RenderFailure as exc:
            failure = exc.code
        except DomainError:
            failure = "private_storage_unavailable"
        except Exception:
            failure = "rendering_failed"
    # Expensive rendering and provider I/O do not hold locks on staff/business actions.
    async with sessions() as s, s.begin():
        initial = await s.get(Export, claim[0])
        assert initial
        await s.scalar(
            select(Account)
            .where(Account.identity_id == initial.requested_by)
            .with_for_update(read=True)
        )
        await s.scalar(
            select(Requisition)
            .where(Requisition.id == initial.requisition_id)
            .with_for_update(read=True)
        )
        row = await s.scalar(
            select(Export)
            .where(Export.id == claim[0])
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not row or row.status != "running" or row.lease_token != claim[1]:
            return
        if not await permitted(s, row):
            failure = "access_changed"
        row.lease_until, row.lease_token = None, None
        if failure:
            row.status = (
                "cancelled"
                if failure == "access_changed"
                else "pending"
                if row.attempts < 3
                and failure in {"private_storage_unavailable", "rendering_failed"}
                else "failed"
            )
            row.last_error = failure
            row.available_at = datetime.now(UTC) + timedelta(
                seconds=min(30 * 2 ** (row.attempts - 1), 300)
            )
            await audit(s, row, "failure")
            logger.warning(
                "requisition.export.failed", extra={"export_id": str(row.id), "reason": failure}
            )
        else:
            assert result
            (
                row.storage_key,
                row.object_version,
                row.file_digest,
                row.byte_size,
                row.renderer_version,
                row.font_version,
            ) = result
            row.status, row.generated_at, row.last_error = "ready", generated_at, None
            await audit(s, row, "success")


async def export_loop(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage: Storage,
    renderer: Renderer = render,
) -> None:
    while True:
        worked = False
        try:
            claim = await claim_job(sessions)
            if claim:
                await process_claim(sessions, settings, storage, claim, renderer)
                worked = True
        except Exception:
            logger.error("requisition.export.worker_failed")
        await asyncio.sleep(0.5 if worked else 2)
