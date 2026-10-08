"""Trusted configuration-operator command; not a public or self-service permission API."""

import asyncio
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.access.models import ReviewGrant
from app.audit.service import AuditDetails, record_event
from app.core.config import get_settings
from app.core.database import make_engine
from app.core.errors import DomainError
from app.identity.models import Account
from app.organisation.models import Entity, Office


async def configure(s: AsyncSession, email: str, entity_id: UUID, active: bool) -> None:
    account = await s.scalar(
        select(Account).where(Account.email == email.strip().lower()).with_for_update()
    )
    entity = await s.get(Entity, entity_id)
    if not account or not entity:
        raise DomainError("VALIDATION_FAILED", "Select an existing account and company.", 422)
    if active and (not account.active or account.password_pending or not entity.active):
        raise DomainError(
            "VALIDATION_FAILED",
            "Grant access only to an activated account and active company.",
            422,
        )
    if active and await s.scalar(
        select(Office.id).where(Office.identity_id == account.identity_id, Office.active.is_(True))
    ):
        raise DomainError(
            "AUTHORITY_ASSIGNMENT_BLOCKED",
            "Revoke financial appointments before granting read-only audit review.",
        )
    grant = await s.scalar(
        select(ReviewGrant)
        .where(ReviewGrant.identity_id == account.identity_id, ReviewGrant.entity_id == entity_id)
        .with_for_update()
    )
    if grant:
        grant.active = active
    elif active:
        s.add(ReviewGrant(identity_id=account.identity_id, entity_id=entity_id))
    await s.flush()
    permissions = set(account.permissions)
    if active:
        account.read_only = True
        permissions.add("audit:read")
    elif not await s.scalar(
        select(ReviewGrant.id)
        .where(ReviewGrant.identity_id == account.identity_id, ReviewGrant.active.is_(True))
        .limit(1)
    ):
        permissions.discard("audit:read")
    account.permissions = sorted(permissions)
    await record_event(
        s,
        action="access.permission_change.success",
        actor_id=None,
        resource_id=account.identity_id,
        entity_id=entity_id,
        details=AuditDetails(changed_fields=["account_state"]),
    )


async def main() -> None:
    email = input("Existing reviewer email: ").strip().lower()
    try:
        entity_id = UUID(input("Company UUID from Organisation & Authority: ").strip())
    except ValueError:
        raise SystemExit("Invalid company UUID") from None
    command = input("Type grant or revoke for this company: ").strip()
    if command not in {"grant", "revoke"}:
        raise SystemExit("No change made")
    engine = make_engine(get_settings())
    try:
        async with async_sessionmaker(engine)() as s, s.begin():
            await configure(s, email, entity_id, command == "grant")
        print("Audit review scope updated. The account stays read-only after revocation.")
    except DomainError as exc:
        raise SystemExit(exc.message) from None
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
