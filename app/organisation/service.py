from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError
from app.identity.models import Account
from app.organisation.models import Department, Entity, Membership, Office


async def membership(session: AsyncSession, identity_id: UUID, entity_id: UUID) -> Membership:
    member = await session.scalar(
        select(Membership)
        .join(Entity, Entity.id == Membership.entity_id)
        .join(Department, Department.id == Membership.department_id)
        .where(
            Entity.active.is_(True),
            Department.active.is_(True),
            Membership.identity_id == identity_id,
            Membership.entity_id == entity_id,
            Membership.active.is_(True),
        )
        .with_for_update(of=[Membership, Entity, Department], read=True)
    )
    if not member:
        raise DomainError("ACCESS_DENIED", "No active membership for this company.", 403)
    return member


def eligible_offices() -> Select[tuple[Office]]:
    now = datetime.now(UTC)
    return (
        select(Office)
        .join(Account, Account.identity_id == Office.identity_id)
        .join(Entity, Entity.id == Office.entity_id)
        .join(
            Membership,
            (Membership.identity_id == Office.identity_id)
            & (Membership.entity_id == Office.entity_id),
        )
        .join(Department, Department.id == Membership.department_id)
        .where(
            Office.active.is_(True),
            Entity.active.is_(True),
            Membership.active.is_(True),
            Department.active.is_(True),
            or_(Office.role != "hod", Office.department_id == Membership.department_id),
            Account.active.is_(True),
            Account.read_only.is_(False),
            Account.password_pending.is_(False),
            Office.valid_from <= now,
            or_(Office.valid_until.is_(None), Office.valid_until > now),
        )
    )


async def has_approval_office(session: AsyncSession, identity_id: UUID) -> bool:
    """Navigation capability, independent of queue size; each decision still checks its assignment."""
    return (
        await session.scalar(
            eligible_offices()
            .where(
                Office.identity_id == identity_id,
                Office.role.in_(["hod", "chief_of_staff", "md", "secretary", "chairman"]),
            )
            .limit(1)
        )
        is not None
    )


async def active_offices(session: AsyncSession, entity_id: UUID) -> list[Office]:
    return list(
        (
            await session.scalars(
                eligible_offices()
                .where(Office.entity_id == entity_id)
                .with_for_update(of=[Office, Membership, Entity, Department, Account], read=True)
            )
        ).all()
    )


async def officeholder(
    session: AsyncSession, entity_id: UUID, role: str, department_id: UUID | None = None
) -> Office:
    candidates = [
        o
        for o in await active_offices(session, entity_id)
        if o.role == role and (role != "hod" or o.department_id == department_id)
    ]
    if len(candidates) != 1:
        raise DomainError(
            "AUTHORITY_ASSIGNMENT_BLOCKED",
            f"A unique active {role.replace('_', ' ')} appointment is required.",
        )
    return candidates[0]
