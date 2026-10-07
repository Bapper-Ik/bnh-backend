"""Public reset requests and protected invitation issuance for account screens."""

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.audit.service import record_event
from app.core.database import Identity, get_session
from app.core.errors import DomainError
from app.identity.email_delivery import queue_link, request_link, require_delivery
from app.identity.models import Account, RecoveryToken
from app.identity.schemas import (
    AccountLink,
    ForgotPassword,
    InvitationView,
    InviteAccount,
    LinkStatus,
    Message,
)
from app.identity.service import (
    Actor,
    current_actor,
    digest,
    hasher,
    require_origin,
    require_permission,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/forgot-password", response_model=Message, status_code=202)
async def forgot_password(
    body: ForgotPassword,
    request: Request,
    session: AsyncSession = Depends(get_session, scope="function"),
) -> Message | JSONResponse:
    require_origin(request)
    if not await request_link(session, str(body.email), request.app.state.settings):
        return JSONResponse(
            status_code=429,
            content={
                "code": "RATE_LIMITED",
                "message": "Please try again later.",
                "request_id": request.state.request_id,
            },
        )
    return Message(
        message="If this email belongs to an eligible account, a password link will be sent. Check your inbox and spam folder."
    )


@router.post("/link-status", response_model=LinkStatus)
async def link_status(
    body: AccountLink,
    request: Request,
    session: AsyncSession = Depends(get_session, scope="function"),
) -> LinkStatus:
    require_origin(request)
    row = (
        await session.execute(
            select(RecoveryToken, Account)
            .join(Account, RecoveryToken.account_id == Account.id)
            .where(RecoveryToken.token_hash == digest(body.token))
        )
    ).one_or_none()
    if not row:
        raise DomainError(
            "RECOVERY_INVALID", "This link is invalid or expired. Request a new link.", 400
        )
    token, account = row
    if (
        not account.active
        or token.consumed_at
        or token.expires_at <= datetime.now(UTC)
        or (token.purpose == "activate") != account.password_pending
    ):
        raise DomainError(
            "RECOVERY_INVALID", "This link is invalid or expired. Request a new link.", 400
        )
    return LinkStatus(purpose=token.purpose)


@router.post("/invitations", response_model=InvitationView, status_code=201)
async def invite(
    body: InviteAccount,
    request: Request,
    actor: Actor = Depends(current_actor),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> InvitationView:
    require_permission(actor, "staff:manage")
    require_delivery(request.app.state.settings)
    email, name = str(body.email).lower(), body.name.strip()
    if len(name) < 2:
        raise DomainError("VALIDATION_FAILED", "Supply the staff member's full name.", 422)
    # Unique email is also protected by the database; serialise concurrent invites.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:email, 913))"), {"email": email}
    )
    account = await session.scalar(select(Account).where(Account.email == email).with_for_update())
    if account:
        if not account.active or not account.password_pending:
            raise DomainError(
                "INVITATION_CONFLICT",
                "This account cannot be invited. Manage its existing account instead.",
                409,
            )
    else:
        identity = Identity(display_name=name)
        session.add(identity)
        await session.flush()
        account = Account(
            identity_id=identity.id,
            email=email,
            password_hash=await run_in_threadpool(hasher.hash, secrets.token_urlsafe(48)),
            password_pending=True,
            permissions=[],
        )
        session.add(account)
        await session.flush()
        await record_event(
            session, action="identity.created", actor_id=actor.id, resource_id=identity.id
        )
    await queue_link(session, account, request.app.state.settings)
    await record_event(
        session, action="auth.invited", actor_id=actor.id, resource_id=account.identity_id
    )
    return InvitationView(identity_id=account.identity_id, email=account.email)
