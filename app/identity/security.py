"""Self-service account security; never accepts authority or profile edits."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.audit.service import AuditDetails, record_event
from app.core.database import get_session
from app.core.errors import DomainError
from app.identity.models import LoginSession, RecoveryToken
from app.identity.recovery import revoke_sessions
from app.identity.schemas import Command, Message
from app.identity.service import Actor, authenticate, current_actor, hasher
from app.organisation.models import Department, Entity, Membership, Office
from app.organisation.service import eligible_offices

router = APIRouter(prefix="/api/v1/auth", tags=["Account security"])


class AccountMembership(BaseModel):
    company: str
    department: str
    active: bool


class AccountOffice(BaseModel):
    company: str
    role: str


class AccountProfile(BaseModel):
    name: str
    email: str
    read_only: bool
    memberships: list[AccountMembership]
    offices: list[AccountOffice]


class SessionView(BaseModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    current: bool


class SessionPage(BaseModel):
    items: list[SessionView]
    total: int
    limit: int
    offset: int


class ChangePassword(Command):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


def clear_cookies(response: Response) -> None:
    response.delete_cookie("custodian_session", path="/")
    response.delete_cookie("custodian_csrf", path="/")


@router.get("/profile", response_model=AccountProfile)
async def profile(
    response: Response,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> AccountProfile:
    rows = (
        await s.execute(
            select(
                Entity.name, Department.name, Membership.active, Entity.active, Department.active
            )
            .select_from(Membership)
            .join(Entity, Entity.id == Membership.entity_id)
            .join(Department, Department.id == Membership.department_id)
            .where(Membership.identity_id == actor.id)
            .order_by(Entity.name, Department.name)
        )
    ).all()
    offices = (
        await s.execute(
            eligible_offices()
            .where(Office.identity_id == actor.id)
            .with_only_columns(Entity.name, Office.role)
            .order_by(Entity.name, Office.role)
        )
    ).all()
    response.headers["Cache-Control"] = "no-store"
    return AccountProfile(
        name=actor.identity.display_name,
        email=actor.account.email,
        read_only=actor.account.read_only,
        memberships=[
            AccountMembership(company=e, department=d, active=m and ea and da)
            for e, d, m, ea, da in rows
        ],
        offices=[AccountOffice(company=e, role=role) for e, role in offices],
    )


@router.get("/sessions", response_model=SessionPage)
async def sessions(
    response: Response,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=100000),
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> SessionPage:
    scope = (
        LoginSession.account_id == actor.account.id,
        LoginSession.revoked.is_(False),
        LoginSession.expires_at > datetime.now(UTC),
    )
    total = await s.scalar(select(func.count()).select_from(LoginSession).where(*scope)) or 0
    rows = (
        await s.scalars(
            select(LoginSession)
            .where(*scope)
            .order_by(
                (LoginSession.id == actor.login_session.id).desc(),
                LoginSession.created_at.desc(),
                LoginSession.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    response.headers["Cache-Control"] = "no-store"
    return SessionPage(
        items=[
            SessionView(
                id=r.id,
                created_at=r.created_at,
                expires_at=r.expires_at,
                current=r.id == actor.login_session.id,
            )
            for r in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/sessions/revoke-others", response_model=Message)
async def revoke_others(
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> Message:
    await s.execute(
        update(LoginSession)
        .where(
            LoginSession.account_id == actor.account.id, LoginSession.id != actor.login_session.id
        )
        .values(revoked=True)
    )
    await record_event(
        s, action="auth.other_sessions_revoked", actor_id=actor.id, resource_id=actor.id
    )
    return Message(message="Other sessions signed out.")


@router.post("/sessions/{session_id}/revoke", response_model=Message)
async def revoke_one(
    session_id: UUID,
    response: Response,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> Message:
    target = await s.scalar(
        select(LoginSession).where(
            LoginSession.id == session_id, LoginSession.account_id == actor.account.id
        )
    )
    if not target:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Session not found.", 404)
    if not target.revoked:
        target.revoked = True
        await record_event(
            s,
            action="auth.session_revoked",
            actor_id=actor.id,
            resource_id=actor.id,
            details=AuditDetails(changed_fields=["session"]),
        )
    if target.id == actor.login_session.id:
        clear_cookies(response)
    return Message(message="Session signed out.")


@router.post("/password", response_model=Message)
async def change_password(
    body: ChangePassword,
    request: Request,
    response: Response,
    actor: Actor = Depends(current_actor),
    s: AsyncSession = Depends(get_session, scope="function"),
) -> Message | JSONResponse:
    account, limited = await authenticate(
        s, actor.account.email, body.current_password, bucket=f"password-change:{actor.account.id}"
    )
    if not account:
        # Return instead of raising so failed-attempt throttling and audit commit.
        return JSONResponse(
            status_code=429 if limited else 400,
            content={
                "code": "RATE_LIMITED" if limited else "PASSWORD_INCORRECT",
                "message": "Please try again later."
                if limited
                else "Current password is incorrect.",
                "request_id": request.state.request_id,
            },
        )
    if body.current_password == body.new_password:
        raise DomainError("VALIDATION_FAILED", "Choose a different new password.", 422)
    account.password_hash = await run_in_threadpool(hasher.hash, body.new_password)
    await s.execute(
        update(RecoveryToken)
        .where(RecoveryToken.account_id == account.id, RecoveryToken.consumed_at.is_(None))
        .values(consumed_at=datetime.now(UTC))
    )
    await revoke_sessions(s, account, actor.id)
    await record_event(
        s,
        action="auth.password_changed",
        actor_id=actor.id,
        resource_id=actor.id,
        details=AuditDetails(changed_fields=["password", "session"]),
    )
    clear_cookies(response)
    return Message(message="Password changed. Sign in again on each device.")
