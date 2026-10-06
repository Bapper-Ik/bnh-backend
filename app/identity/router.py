import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.permissions import ADMIN_PERMISSIONS, READ_PERMISSIONS
from app.audit.service import record_event
from app.core.database import Identity, get_session
from app.core.errors import DomainError
from app.identity.models import Account, LoginSession
from app.identity.recovery import recover, revoke_sessions
from app.identity.schemas import AccountCreate, Login, Message, Reauthenticate, Recover, UserView
from app.identity.service import (
    Actor,
    authenticate,
    current_actor,
    digest,
    hasher,
    require_origin,
    require_permission,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


def user_view(actor: Actor) -> UserView:
    return UserView(
        id=actor.id,
        account_id=actor.account.id,
        name=actor.identity.display_name,
        email=actor.account.email,
        permissions=sorted(
            set(actor.account.permissions)
            & ADMIN_PERMISSIONS
            & (READ_PERMISSIONS if actor.account.read_only else ADMIN_PERMISSIONS)
        ),
        read_only=actor.account.read_only,
    )


@router.post("/login", response_model=UserView)
async def login(
    body: Login,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session, scope="function"),
) -> UserView | JSONResponse:
    require_origin(request)
    account, limited = await authenticate(session, str(body.email), body.password)
    if not account:
        return JSONResponse(
            status_code=429 if limited else 401,
            content={
                "code": "RATE_LIMITED" if limited else "AUTHENTICATION_REQUIRED",
                "message": "Please try again later."
                if limited
                else "Email or password is incorrect.",
                "request_id": request.state.request_id,
            },
        )
    now = datetime.now(UTC)
    token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    auth = LoginSession(
        account_id=account.id,
        token_hash=digest(token),
        csrf_hash=digest(csrf),
        expires_at=now + timedelta(hours=request.app.state.settings.session_hours),
        authenticated_at=now,
    )
    session.add(auth)
    await record_event(session, action="auth.signed_in", actor_id=account.identity_id)
    # Flush before setting cookies; the dependency commits before response delivery.
    await session.flush()
    secure = request.app.state.settings.cookie_secure
    for name, value, http_only in [
        ("custodian_session", token, True),
        ("custodian_csrf", csrf, False),
    ]:
        response.set_cookie(
            name,
            value,
            httponly=http_only,
            secure=secure,
            samesite="lax",
            path="/",
            max_age=request.app.state.settings.session_hours * 3600,
        )
    identity = await session.get(Identity, account.identity_id)
    assert identity
    return user_view(Actor(account, identity, auth))


@router.get("/me", response_model=UserView)
async def me(actor: Actor = Depends(current_actor)) -> UserView:
    return user_view(actor)


@router.post("/logout", response_model=Message)
async def logout(
    response: Response,
    actor: Actor = Depends(current_actor),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> Message:
    actor.login_session.revoked = True
    await record_event(session, action="auth.signed_out", actor_id=actor.id)
    response.delete_cookie("custodian_session", path="/")
    response.delete_cookie("custodian_csrf", path="/")
    return Message(message="Signed out.")


@router.post("/reauthenticate", response_model=Message)
async def reauthenticate(
    body: Reauthenticate,
    request: Request,
    actor: Actor = Depends(current_actor),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> Message | JSONResponse:
    account, limited = await authenticate(
        session, actor.account.email, body.password, bucket=f"reauth:{actor.account.id}"
    )
    if not account:
        return JSONResponse(
            status_code=429 if limited else 401,
            content={
                "code": "RATE_LIMITED" if limited else "AUTHENTICATION_REQUIRED",
                "message": "Please try again later." if limited else "Password is incorrect.",
                "request_id": request.state.request_id,
            },
        )
    actor.login_session.authenticated_at = datetime.now(UTC)
    await record_event(session, action="auth.reauthenticated", actor_id=actor.id)
    return Message(message="Identity confirmed.")


@router.post("/recover", response_model=Message)
async def complete_recovery(
    body: Recover, request: Request, session: AsyncSession = Depends(get_session, scope="function")
) -> Message | JSONResponse:
    require_origin(request)
    if not await recover(session, body.token, body.password):
        return JSONResponse(
            status_code=400,
            content={
                "code": "RECOVERY_INVALID",
                "message": "The recovery link is invalid or expired.",
                "request_id": request.state.request_id,
            },
        )
    return Message(message="Password updated. Sign in again.")


@router.post("/sessions/revoke", response_model=Message)
async def revoke_own_sessions(
    response: Response,
    actor: Actor = Depends(current_actor),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> Message:
    await revoke_sessions(session, actor.account, actor.id)
    response.delete_cookie("custodian_session", path="/")
    response.delete_cookie("custodian_csrf", path="/")
    return Message(message="All sessions signed out.")


@router.post("/accounts/{identity_id}/revoke-sessions", response_model=Message)
async def revoke_account_sessions(
    identity_id: UUID,
    actor: Actor = Depends(current_actor),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> Message:
    require_permission(actor, "staff:manage")
    account = await session.scalar(
        select(Account).where(Account.identity_id == identity_id).with_for_update()
    )
    if not account:
        raise DomainError("RESOURCE_NOT_AVAILABLE", "Account not found.", 404)
    await revoke_sessions(session, account, actor.id)
    return Message(message="Account sessions revoked.")


@router.post("/accounts", response_model=UserView, status_code=201)
async def provision_account(
    body: AccountCreate,
    actor: Actor = Depends(current_actor),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> UserView:
    from starlette.concurrency import run_in_threadpool

    require_permission(actor, "staff:manage")
    name, email = body.name.strip(), str(body.email).lower()
    if len(name) < 2:
        raise DomainError("VALIDATION_FAILED", "Supply the staff member's full name.", 422)
    if await session.scalar(select(Account.id).where(Account.email == email)):
        raise DomainError("VALIDATION_FAILED", "An account already uses that email.", 422)
    identity = Identity(display_name=name)
    session.add(identity)
    await session.flush()
    account = Account(
        identity_id=identity.id,
        email=email,
        password_hash=await run_in_threadpool(hasher.hash, body.initial_password),
        permissions=[],
    )
    session.add(account)
    await session.flush()
    await record_event(
        session, action="identity.created", actor_id=actor.id, resource_id=identity.id
    )
    return UserView(id=identity.id, account_id=account.id, name=name, email=email, permissions=[])
